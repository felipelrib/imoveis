import os

"""
Integration tests for the Real-Estate ingestion system.
Tests cover API endpoints, deduplication, scraping, and async task processing.

Run with: pytest src/tests/integration/ -v
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Assuming project is added to PYTHONPATH or run from project root
from adapters.db.models import Base, MetricsScoring, PriceHistory, Property
from adapters.queue.gpu_semaphore import GPUSemaphore
from adapters.scrapers.base import BaseScraper
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from api.main import app
from core.dedupe import match_or_create_property
from core.entities import PropertyCandidate

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(scope="function")
def test_db():
    """Connect to the test database and provide a session.

    DATABASE_URL must be set by the test runner (validate.sh guarantees this).
    Truncates all tables after each test for isolation.
    """
    import os

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integrate with validate.sh or set manually")

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    # Truncate all tables for test isolation
    with engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="function")
def test_client():
    """Create a TestClient for FastAPI app."""
    return TestClient(app)


@pytest.fixture(scope="function")
def mock_redis():
    """Use real Redis from CI when available, otherwise mock it."""
    import os

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        import redis

        client = redis.Redis.from_url(redis_url)
        client.flushdb()
        yield client
        client.flushdb()
        client.close()
    else:
        with patch("redis.Redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            yield mock_client


# ============================================================================
# API Tests
# ============================================================================


class TestAPIEndpoints:
    """Test FastAPI endpoints."""

    def test_health_check(self, test_client):
        """Verify health check endpoint responds OK."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        # Status may be "ok" or "degraded" depending on available services
        assert data["status"] in ("ok", "degraded")

    def test_index_endpoint(self, test_client):
        """Verify index endpoint returns service info."""
        response = test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert data["service"] == "local-realestate"
        assert data["status"] == "running"

    def test_admin_health(self, test_client):
        """Verify admin health endpoint."""
        response = test_client.get("/admin/health", headers={"X-API-Key": os.environ.get("API_KEY", "dev_admin_key_123")})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_admin_workers_status(self, test_client, mock_redis):
        """Verify admin workers status endpoint."""
        response = test_client.get("/admin/workers/status", headers={"X-API-Key": os.environ.get("API_KEY", "dev_admin_key_123")})
        assert response.status_code == 200
        data = response.json()
        assert "ai_workers_paused" in data
        assert isinstance(data["ai_workers_paused"], bool)

    def test_pause_workers(self, test_client, mock_redis):
        """Test pausing AI workers."""
        response = test_client.post("/admin/workers/pause", headers={"X-API-Key": os.environ.get("API_KEY", "dev_admin_key_123")})
        assert response.status_code == 200
        assert response.json() == {"paused": True}

    def test_resume_workers(self, test_client, mock_redis):
        """Test resuming AI workers."""
        response = test_client.post("/admin/workers/resume", headers={"X-API-Key": os.environ.get("API_KEY", "dev_admin_key_123")})
        assert response.status_code == 200
        assert response.json() == {"paused": False}

    def test_gpu_scale_endpoint(self, test_client, mock_redis):
        """Test GPU scaling endpoint."""
        response = test_client.post(
            "/admin/gpu/scale",
            json={"limit": 2},
            headers={"X-API-Key": os.environ.get("API_KEY", "dev_admin_key_123")},
        )
        assert response.status_code == 200
        assert response.json() == {"gpu_limit": 2}


# ============================================================================
# Deduplication Tests
# ============================================================================


class TestDeduplication:
    """Test deduplication logic."""

    def test_create_new_property(self, test_db):
        """Test creating a new property when no duplicate exists."""
        incoming = {
            "platform": "quintoandar",
            "platform_id": "123456",
            "title": "Beautiful 2BR Apartment",
            "description": "Spacious 2-bedroom apartment in downtown.",
            "price": 150000.0,
            "area_m2": 85.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A, 100, São Paulo, SP",
            "props_json": {"raw": "data"},
        }

        result = match_or_create_property(test_db, PropertyCandidate(**incoming))

        assert result.action == "created"
        assert result.property_id is not None

        # Verify property was persisted
        prop = test_db.query(Property).filter_by(platform_id="123456").first()
        assert prop is not None
        assert prop.title == "Beautiful 2BR Apartment"
        assert prop.price == 150000.0

    def test_duplicate_detection_same_location_and_specs(self, test_db):
        """Test detecting a duplicate property with same location and specs."""
        # Create first property
        incoming1 = {
            "platform": "quintoandar",
            "platform_id": "111",
            "title": "2BR Apt",
            "description": "Spacious apartment.",
            "price": 150000.0,
            "area_m2": 85.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A, 100",
            "props_json": {"raw": "data1"},
        }
        result1 = match_or_create_property(test_db, PropertyCandidate(**incoming1))
        assert result1.action == "created"

        # Try to ingest same property (duplicate)
        incoming2 = {
            "platform": "olx",
            "platform_id": "222",
            "title": "2BR Apt",
            "description": "Spacious apartment.",
            "price": 150000.0,  # Same price
            "area_m2": 85.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A, 100",
            "props_json": {"raw": "data2"},
        }
        result2 = match_or_create_property(test_db, PropertyCandidate(**incoming2), radius_m=50, text_threshold=0.6)
        assert result2.action == "updated"
        assert result2.property_id == result1.property_id

    def test_price_change_tracking(self, test_db):
        """Test that price changes are tracked in history."""
        # Create property
        incoming1 = {
            "platform": "quintoandar",
            "platform_id": "123",
            "title": "Apt",
            "description": "Description.",
            "price": 100000.0,
            "area_m2": 80.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A",
            "props_json": {},
        }
        result1 = match_or_create_property(test_db, PropertyCandidate(**incoming1))
        prop_id = result1.property_id

        # Update with new price
        incoming2 = {
            "platform": "quintoandar",
            "platform_id": "123",
            "title": "Apt",
            "description": "Description.",
            "price": 120000.0,  # Price increased
            "area_m2": 80.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A",
            "props_json": {},
        }
        result2 = match_or_create_property(test_db, PropertyCandidate(**incoming2))

        assert result2.action == "updated"
        assert result2.property_id == prop_id

        # Verify price history
        history = test_db.query(PriceHistory).filter_by(property_id=prop_id).all()
        assert len(history) > 0
        assert history[0].price == 100000.0  # Old price recorded


# ============================================================================
# Circuit Breaker Tests
# ============================================================================


class TestCircuitBreaker:
    """Test circuit breaker pattern for resilience."""

    def test_circuit_breaker_opens_on_failures(self):
        """Test that circuit breaker opens after threshold failures."""
        import os

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            pytest.skip("REDIS_URL not set — skipping Redis-dependent test")

        cb = RedisCircuitBreaker(platform="test", failure_threshold=3, cooldown_seconds=60)

        assert not cb.is_open()

        # Record 2 failures (below threshold)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open()

        # Record 3rd failure (threshold met)
        cb.record_failure()
        assert cb.is_open()

    def test_circuit_breaker_resets_on_success(self):
        """Test that circuit breaker resets on success."""
        import os

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            pytest.skip("REDIS_URL not set — skipping Redis-dependent test")

        cb = RedisCircuitBreaker(platform="test", failure_threshold=2, cooldown_seconds=1)

        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()

        cb.record_success()
        assert not cb.is_open()


# ============================================================================
# GPU Semaphore Tests
# ============================================================================


class TestGPUSemaphore:
    """Test GPU resource semaphore."""

    def test_semaphore_basic_acquire_release(self, mock_redis):
        """Test basic semaphore acquire and release."""
        import os

        # This test requires a real Redis connection because GPUSemaphore uses
        # Redis pipelines internally. The mock fixture returns a MagicMock when
        # REDIS_URL is not set, which cannot simulate pipeline transactions.
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            pytest.skip("REDIS_URL not set — semaphore test requires real Redis")

        sem = GPUSemaphore(name="gpu", max_concurrent=1)

        # Use real Redis for acquire/release
        acquired = sem.acquire(timeout=5)
        assert acquired is True

        assert sem.available == 0

        sem.release()
        assert sem.available == 1


# ============================================================================
# Scraper Interface Tests
# ============================================================================


class TestScraperInterface:
    """Test scraper base interface and implementations."""

    def test_base_scraper_interface(self):
        """Test that BaseScraper enforces required methods."""

        class MinimalScraper(BaseScraper):
            def start(self):
                pass

            def fetch_pages(self, checkpoint):
                yield {"id": 1, "price": 100}

            def normalize(self, raw):
                return {"platform_id": raw["id"]}

        scraper = MinimalScraper("test", {})
        scraper.start()

        pages = list(scraper.fetch_pages({}))
        assert len(pages) == 1

        normalized = scraper.normalize(pages[0])
        assert "platform_id" in normalized

    def test_scraper_with_checkpoint(self):
        """Test scraper checkpoint persistence."""

        class PagedScraper(BaseScraper):
            def __init__(self, platform_name: str, config: dict):
                super().__init__(platform_name, config)
                self.max_pages = 3

            def start(self):
                pass

            def fetch_pages(self, checkpoint):
                page = checkpoint.get("page", 1)
                while page <= self.max_pages:
                    yield {"page": page, "items": []}
                    page += 1
                    checkpoint["page"] = page

            def normalize(self, raw):
                return raw

        scraper = PagedScraper("test", {})
        checkpoint = {"page": 1}
        scraper.start()

        pages = []
        for page_data in scraper.fetch_pages(checkpoint):
            pages.append(page_data)

        assert len(pages) == 3
        assert checkpoint["page"] == 4  # Advanced by fetch_pages


# ============================================================================
# Metrics Scoring Tests
# ============================================================================


class TestMetricsScoring:
    """Test scoring and metrics computation."""

    def test_create_metrics_scoring_record(self, test_db):
        """Test creating a MetricsScoring record."""
        # Create a property first
        prop = Property(
            platform="quintoandar",
            platform_id="123",
            title="Apt",
            price=100000.0,
        )
        test_db.add(prop)
        test_db.commit()

        # Create scoring record
        scoring = MetricsScoring(
            property_id=prop.id,
            stat_score=0.65,
            ai_score=0.72,
            combined_score=0.685,
            meta={"neighborhood": "Downtown", "condition": "Good"},
        )
        test_db.add(scoring)
        test_db.commit()

        # Verify
        result = test_db.query(MetricsScoring).filter_by(property_id=prop.id).first()
        assert result is not None
        assert result.stat_score == 0.65
        assert result.ai_score == 0.72
        assert result.combined_score == 0.685


# ============================================================================
# End-to-End Workflow Tests
# ============================================================================


class TestEndToEndWorkflow:
    """Test complete ingestion workflow."""

    def test_full_ingestion_workflow(self, test_db):
        """Test complete workflow: ingest → dedupe → score."""
        # Step 1: Ingest first property
        prop1_data = {
            "platform": "quintoandar",
            "platform_id": "prop_1",
            "title": "2BR Downtown",
            "description": "Modern 2-bedroom apartment.",
            "price": 150000.0,
            "area_m2": 85.0,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A, 100",
            "props_json": {"images": ["img1.jpg"]},
        }

        result1 = match_or_create_property(test_db, PropertyCandidate(**prop1_data))
        assert result1.action == "created"
        prop1_id = result1.property_id

        # Step 2: Create scoring record
        scoring1 = MetricsScoring(
            property_id=prop1_id,
            stat_score=0.7,
            ai_score=0.8,
            combined_score=0.75,
        )
        test_db.add(scoring1)
        test_db.commit()

        # Step 3: Ingest duplicate from different platform
        prop2_data = {
            "platform": "olx",
            "platform_id": "prop_2",
            "title": "2BR Downtown Apt",
            "description": "Modern 2-bedroom apartment.",
            "price": 145000.0,  # Slightly different price
            "area_m2": 84.5,
            "bedrooms": 2,
            "bathrooms": 1,
            "parking": 1,
            "location": {"lat": -23.5505, "lon": -46.6333},
            "address": "Rua A, 100",
            "props_json": {"images": ["img2.jpg"]},
        }

        result2 = match_or_create_property(
            test_db,
            PropertyCandidate(**prop2_data),
            radius_m=50,
            area_tol=2.0,
            text_threshold=0.6,
        )

        # Should match as duplicate (updated)
        assert result2.action == "updated"
        assert result2.property_id == prop1_id

        # Verify price history
        histories = test_db.query(PriceHistory).filter_by(property_id=prop1_id).all()
        assert len(histories) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
