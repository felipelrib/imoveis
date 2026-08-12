"""API contract tests — validate response shapes for every endpoint.

These tests ensure that the API's response schema doesn't change without
updating this contract. Uses FastAPI TestClient with minimal dependencies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from api.main import app
from api.schemas import PropertyModel
from infra.config import get_config

_TEST_API_KEY = "contract-test-api-key"


def _properties_schema_ready() -> bool:
    """True when the properties table is queryable (migrated DB)."""
    try:
        from infra.db import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1 FROM properties LIMIT 0"))
        return True
    except Exception:
        return False


def _assert_ok_or_skip_infra(response, *, endpoint: str):
    """Fail on application/schema 500s; skip only when DB schema is missing.

    BIN-56: swallowing all 500s hid ResponseValidationError when AI float
    scores were present. If the table exists, a 500 is a real regression.
    """
    if response.status_code == 200:
        return
    if response.status_code >= 500:
        if _properties_schema_ready():
            pytest.fail(
                f"{endpoint} returned {response.status_code} while properties "
                f"schema is available (likely response validation). "
                f"Body: {response.text[:500]}"
            )
        pytest.skip(f"{endpoint} unavailable — DB/schema not ready")
    pytest.fail(f"Unexpected {endpoint} status {response.status_code}: {response.text[:300]}")


@pytest.fixture(autouse=True)
def _auth_env_for_contracts(monkeypatch: pytest.MonkeyPatch):
    """Wire a known API key through AppConfig for admin contract calls."""
    monkeypatch.setenv("API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("JWT_SECRET", "contract-test-jwt-secret")
    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture
def client():
    """FastAPI TestClient — no DB/Redis needed for schema validation.

    ``raise_server_exceptions=False`` ensures that 500-level errors (e.g.
    from a missing database) are returned as normal HTTP responses instead
    of being re-raised by the test client.
    """
    c = TestClient(app, raise_server_exceptions=False)
    return c


@pytest.fixture
def admin_headers():
    return {"X-API-Key": _TEST_API_KEY}


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_valid_shape(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "error")

    def test_index_returns_valid_shape(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "status" in data
        assert isinstance(data["service"], str)

    def test_properties_list_returns_valid_shape(self, client):
        """Properties endpoint should return a paginated response with items."""
        response = client.get("/properties?page=1&page_size=10")
        _assert_ok_or_skip_infra(response, endpoint="GET /properties")
        data = response.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "properties" in data
        assert isinstance(data["properties"], list)
        for prop in data["properties"]:
            for score_key in ("condition_score", "sentiment_score"):
                val = prop.get(score_key)
                if val is not None:
                    assert isinstance(val, (int, float)), f"{score_key} must be numeric"

    def test_properties_sort_by_price_listing_type_sale(self, client):
        """GET /properties with sort_by=price + listing_type=sale must succeed (BIN-106)."""
        response = client.get(
            "/properties?page=1&page_size=5&sort_by=price&sort_dir=asc&listing_type=sale"
        )
        _assert_ok_or_skip_infra(response, endpoint="GET /properties sort price sale")
        data = response.json()
        assert "properties" in data
        assert isinstance(data["properties"], list)


class TestPlatformsEndpoint:
    def test_platforms_returns_list(self, client):
        """GET /platforms must return a list of platform objects."""
        response = client.get("/platforms")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Each item should be a dict with name and enabled fields
        for platform in data:
            assert isinstance(platform, dict)
            assert "name" in platform
            assert "enabled" in platform
            assert isinstance(platform["name"], str)
            assert isinstance(platform["enabled"], bool)


class TestScrapeEndpoint:
    """POST /scrape must require admin credentials (BIN-149).

    Prior to this fix the route had no ``Depends(verify_admin_access)`` (or
    any auth check) at all, so any unauthenticated caller could enqueue
    scrape jobs against QuintoAndar/OLX/ZapImóveis for any registered
    platform. These are the regression specs for that fix.
    """

    def test_scrape_without_credential_returns_401(self, client):
        response = client.post("/scrape", json={"platform": "olx"})
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_scrape_with_invalid_credential_returns_403(self, client):
        response = client.post(
            "/scrape",
            json={"platform": "olx"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 403

    def test_scrape_with_valid_credential_enqueues(self, client, admin_headers, monkeypatch):
        """A correctly-credentialed request still reaches the enqueue path."""
        from adapters.queue.tasks import scrape_listings

        fake_task = type("FakeTask", (), {"id": "fake-task-id"})()
        monkeypatch.setattr(scrape_listings, "delay", lambda *a, **k: fake_task)

        response = client.post(
            "/scrape",
            json={"platform": "olx"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "olx"
        assert data["status"] == "queued"
        assert data["task_id"] == "fake-task-id"

    def test_scrape_unknown_platform_still_returns_400_when_authorized(self, client, admin_headers):
        """Auth gate must not shadow the existing unknown-platform validation."""
        response = client.post(
            "/scrape",
            json={"platform": "not-a-real-platform"},
            headers=admin_headers,
        )
        assert response.status_code == 400


class TestNeighborhoodsEndpoint:
    def test_neighborhoods_returns_list(self, client):
        """GET /properties/neighborhoods must return a list of neighbourhood objects."""
        response = client.get("/properties/neighborhoods")
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/neighborhoods")
        data = response.json()
        assert isinstance(data, list)
        for item in data:
            assert isinstance(item, dict)
            assert "name" in item
            assert "count" in item
            assert isinstance(item["name"], str)
            assert isinstance(item["count"], int)
            # city may be null for legacy rows without city metadata
            assert "city" in item
            # BIN-86 quality profile keys (nullable / empty until fill jobs run)
            for key in (
                "id",
                "amenity_score",
                "transit_score",
                "access_score",
                "safety_score",
                "risk_flags",
                "quality_meta",
                "quality_notes",
            ):
                assert key in item
            assert isinstance(item["risk_flags"], list)
            for score_key in (
                "amenity_score",
                "transit_score",
                "access_score",
                "safety_score",
            ):
                score = item[score_key]
                if score is not None:
                    assert isinstance(score, (int, float))
                    assert 0.0 <= float(score) <= 1.0

    def test_neighborhood_detail_unknown_id_is_404(self, client):
        response = client.get(
            "/properties/neighborhoods/00000000-0000-0000-0000-000000000000"
        )
        if response.status_code >= 500:
            if not _properties_schema_ready():
                pytest.skip(
                    "GET /properties/neighborhoods/{id} unavailable — DB/schema not ready"
                )
            pytest.fail(
                f"GET /properties/neighborhoods/{{id}} returned {response.status_code} "
                f"while schema is available. Body: {response.text[:500]}"
            )
        assert response.status_code == 404


class TestNeighborhoodModelQualityProfileContract:
    """DB-free lock: quality scores are floats in [0,1]; null = unknown (BIN-86)."""

    def test_neighborhood_model_accepts_fractional_scores(self):
        from api.schemas import NeighborhoodModel

        model = NeighborhoodModel.model_validate(
            {
                "name": "Savassi",
                "count": 2,
                "city": "Belo Horizonte",
                "amenity_score": 0.85,
                "transit_score": 0.4,
                "risk_flags": ["flood"],
                "quality_meta": {"provider": "curated-yaml"},
            }
        )
        assert model.amenity_score == pytest.approx(0.85)
        assert model.transit_score == pytest.approx(0.4)
        assert model.risk_flags == ["flood"]

    def test_neighborhood_model_rejects_out_of_range_score(self):
        from api.schemas import NeighborhoodModel

        with pytest.raises(ValidationError):
            NeighborhoodModel.model_validate(
                {"name": "Savassi", "count": 1, "safety_score": 2.0}
            )


class TestCitiesEndpoint:
    def test_cities_returns_list(self, client):
        """GET /properties/cities must return a list of city objects (BIN-70)."""
        response = client.get("/properties/cities")
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/cities")
        data = response.json()
        assert isinstance(data, list)
        for item in data:
            assert isinstance(item, dict)
            assert "name" in item
            assert "count" in item
            assert isinstance(item["name"], str)
            assert isinstance(item["count"], int)


class TestPropertyModelAiScoreContract:
    """DB-free lock: AI domain scores are floats — schema must accept them (BIN-56)."""

    def test_property_model_accepts_fractional_condition_and_sentiment(self):
        payload = {
            "id": "11111111-1111-1111-1111-111111111111",
            "platform": "test",
            "platform_id": "p1",
            "title": "Apt",
            "price": 1000.0,
            "image_urls": [],
            "condition_score": 0.75,
            "sentiment_score": 0.78,
        }
        model = PropertyModel.model_validate(payload)
        assert model.condition_score == pytest.approx(0.75)
        assert model.sentiment_score == pytest.approx(0.78)

    def test_property_model_accepts_neighbourhood_quality(self):
        payload = {
            "id": "11111111-1111-1111-1111-111111111111",
            "platform": "test",
            "platform_id": "p1",
            "title": "Apt",
            "price": 1000.0,
            "image_urls": [],
            "neighbourhood_quality": {
                "amenity_score": 0.8,
                "transit_score": 0.6,
                "access_score": None,
                "safety_score": 0.7,
                "neighbourhood_score": 0.7,
                "risk_flags": ["flood"],
                "quality_meta": {"source": "curated"},
            },
        }
        model = PropertyModel.model_validate(payload)
        assert model.neighbourhood_quality is not None
        assert model.neighbourhood_quality.neighbourhood_score == pytest.approx(0.7)
        assert model.neighbourhood_quality.risk_flags == ["flood"]


_PROJECTION_KEYS = (
    "id",
    "public_id",
    "price",
    "price_per_m2",
    "price_per_m2_rent",
    "price_per_m2_sale",
    "neighborhood_mean_rent",
    "neighborhood_mean_sale",
    "stat_score_rent",
    "stat_score_sale",
    "combined_score_rent",
    "combined_score_sale",
    "stat_score",
    "ai_score",
    "combined_score",
    "neighborhood_name",
    "neighborhood_id",
    "neighbourhood_quality",
    "primary_listing",
    "listings",
)


def _assert_projection_keys(item: dict) -> None:
    for key in _PROJECTION_KEYS:
        assert key in item, f"missing projection key: {key}"
    assert isinstance(item["listings"], list)
    if item["primary_listing"] is not None:
        assert isinstance(item["primary_listing"], dict)
        assert "price" in item["primary_listing"]
        assert "listing_type" in item["primary_listing"]
        assert "platform" in item["primary_listing"]


class TestPropertyProjectionContract:
    def test_list_items_include_ad12_fields(self, client):
        response = client.get("/properties?page=1&page_size=5")
        _assert_ok_or_skip_infra(response, endpoint="GET /properties")
        data = response.json()
        assert "properties" in data
        for item in data["properties"]:
            _assert_projection_keys(item)

    def test_detail_includes_ad12_fields(self, client):
        list_resp = client.get("/properties?page=1&page_size=1")
        _assert_ok_or_skip_infra(list_resp, endpoint="GET /properties")
        props = list_resp.json().get("properties") or []
        if not props:
            return
        prop_id = props[0]["id"]
        response = client.get(f"/properties/{prop_id}")
        _assert_ok_or_skip_infra(response, endpoint=f"GET /properties/{prop_id}")
        _assert_projection_keys(response.json())

    def test_batch_rejects_empty_ids(self, client):
        response = client.get("/properties/by-ids?ids=")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_rejects_more_than_four_ids(self, client):
        ids = ",".join(
            [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                "33333333-3333-3333-3333-333333333333",
                "44444444-4444-4444-4444-444444444444",
                "55555555-5555-5555-5555-555555555555",
            ]
        )
        response = client.get(f"/properties/by-ids?ids={ids}")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_rejects_malformed_id(self, client):
        response = client.get("/properties/by-ids?ids=not-a-uuid")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_batch_returns_projection_shape(self, client):
        list_resp = client.get("/properties?page=1&page_size=2")
        _assert_ok_or_skip_infra(list_resp, endpoint="GET /properties")
        props = list_resp.json().get("properties") or []
        if not props:
            response = client.get(
                "/properties/by-ids?ids=11111111-1111-1111-1111-111111111111"
            )
            _assert_ok_or_skip_infra(response, endpoint="GET /properties/by-ids")
            data = response.json()
            assert "properties" in data
            assert isinstance(data["properties"], list)
            return

        ids = ",".join(p["id"] for p in props[:2])
        response = client.get(f"/properties/by-ids?ids={ids}")
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/by-ids")
        data = response.json()
        assert "properties" in data
        assert isinstance(data["properties"], list)
        for item in data["properties"]:
            _assert_projection_keys(item)


class TestPropertyExportContract:
    def test_export_rejects_invalid_format(self, client, admin_headers):
        response = client.get("/properties/export?format=xml", headers=admin_headers)
        assert response.status_code == 422

    def test_export_json_shape_and_projection(self, client, admin_headers):
        response = client.get("/properties/export?format=json", headers=admin_headers)
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/export")
        data = response.json()
        assert "properties" in data
        assert "total" in data
        assert "truncated" in data
        assert isinstance(data["properties"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["truncated"], bool)
        assert data["total"] >= len(data["properties"])
        for item in data["properties"]:
            _assert_projection_keys(item)
            for score_key in ("condition_score", "sentiment_score"):
                val = item.get(score_key)
                if val is not None:
                    assert isinstance(val, (int, float)), f"{score_key} must be numeric"

    def test_export_csv_headers_and_empty_ok(self, client, admin_headers):
        response = client.get("/properties/export?format=csv", headers=admin_headers)
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/export csv")
        assert "text/csv" in response.headers.get("content-type", "")
        assert "properties-export.csv" in response.headers.get("content-disposition", "")
        body = response.text
        assert body.startswith("id,")
        assert "primary_listing_price" in body.splitlines()[0]
        assert "X-Export-Total" in response.headers
        assert "X-Export-Truncated" in response.headers

    def test_export_json_empty_result_set(self, client, admin_headers):
        response = client.get(
            "/properties/export?format=json&neighborhood_name=__no_such_nbr_bin50__",
            headers=admin_headers,
        )
        _assert_ok_or_skip_infra(response, endpoint="GET /properties/export empty")
        data = response.json()
        assert data["properties"] == []
        assert data["total"] == 0
        assert data["truncated"] is False

    def test_export_requires_key_when_configured(self, client):
        response = client.get("/properties/export?format=json")
        assert response.status_code == 403
        assert "detail" in response.json()


# ---------------------------------------------------------------------------
# Admin endpoints (contract shape, not auth logic)
# ---------------------------------------------------------------------------

class TestAdminEndpoints:
    def test_health_admin_shape(self, client, admin_headers):
        response = client.get(
            "/admin/health",
            headers=admin_headers,
        )
        data = response.json()
        assert isinstance(data, dict)
        assert response.status_code == 200
        assert data == {"status": "ok"}

    def test_system_status_shape(self, client, admin_headers):
        # BIN-150: /system/status now requires a credential whenever an admin
        # API key is configured (this fixture always configures one).
        response = client.get("/system/status", headers=admin_headers)
        data = response.json()
        assert isinstance(data, dict)

    def test_system_status_requires_key_when_configured(self, client):
        response = client.get("/system/status")
        assert response.status_code == 403
        assert "detail" in response.json()

    def test_schedule_get_returns_shape(self, client, admin_headers):
        """GET /admin/schedule must return a dict with a schedules list."""
        response = client.get(
            "/admin/schedule",
            headers=admin_headers,
        )
        data = response.json()
        if response.status_code == 200:
            assert "schedules" in data
            assert isinstance(data["schedules"], list)
            # Each schedule entry has expected fields
            for entry in data["schedules"]:
                assert "platform" in entry
                assert "interval_minutes" in entry
                assert isinstance(entry["platform"], str)
                assert isinstance(entry["interval_minutes"], int)
        elif response.status_code == 403:
            assert "detail" in data

    def test_locale_get_returns_shape(self, client, admin_headers):
        """GET /admin/locale must return locale, default, and supported list."""
        response = client.get(
            "/admin/locale",
            headers=admin_headers,
        )
        data = response.json()
        if response.status_code == 200:
            assert "locale" in data
            assert "default" in data
            assert "supported" in data
            assert isinstance(data["locale"], str)
            assert isinstance(data["default"], str)
            assert isinstance(data["supported"], list)
            assert data["locale"] in data["supported"]
            assert data["default"] in data["supported"]
        elif response.status_code == 403:
            assert "detail" in data


# ---------------------------------------------------------------------------
# Backfill control plane (v0.13-s1.5)
# ---------------------------------------------------------------------------


class _FakeBackfillRedis:
    """Dict-backed stand-in so the contract shape does not need a live runner."""

    def __init__(self) -> None:
        self.kv: dict = {}
        self.hashes: dict = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    def expire(self, key, ttl):
        return 1 if key in self.kv or key in self.hashes else 0

    def delete(self, key):
        existed = key in self.kv or key in self.hashes
        self.kv.pop(key, None)
        self.hashes.pop(key, None)
        return 1 if existed else 0

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            h[field] = str(value)

    def hincrby(self, key, field, n=1):
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(n))
        return int(h[field])

    def hdel(self, key, *fields):
        for f in fields:
            self.hashes.setdefault(key, {}).pop(f, None)


class TestAdminBackfillControlContract:
    """``/admin/backfill/*``: auth gate first, then the wire shape story 1.6 codes
    against. The runner's Redis is faked — this locks the contract, not a run."""

    _ENDPOINTS = (
        ("get", "/admin/backfill/status"),
        ("post", "/admin/backfill/start"),
        ("post", "/admin/backfill/pause"),
        ("post", "/admin/backfill/resume"),
    )

    @pytest.fixture
    def backfill_redis(self, monkeypatch):
        fake = _FakeBackfillRedis()
        monkeypatch.setattr("api.admin.get_redis", lambda: fake)
        # The audit trail is exercised by the unit tests; here it would need the
        # admin_audit table and says nothing about the response shape.
        monkeypatch.setattr("api.admin.log_audit_action", lambda *a, **k: None)
        return fake

    @pytest.mark.parametrize("method,path", _ENDPOINTS)
    def test_requires_admin_credentials(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 401
        assert "detail" in response.json()

    @pytest.mark.parametrize("method,path", _ENDPOINTS)
    def test_rejects_an_invalid_credential(self, client, method, path):
        response = getattr(client, method)(path, headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 403

    def test_status_matches_the_response_model(self, client, admin_headers, backfill_redis):
        from api.schemas import BackfillStatusResponse

        response = client.get("/admin/backfill/status", headers=admin_headers)
        assert response.status_code == 200, response.text[:300]
        body = BackfillStatusResponse.model_validate(response.json())
        assert body.state in (
            "idle",
            "running",
            "paused",
            "backing-off",
            "blocked",
        )
        assert body.active is False
        assert body.lease is None
        assert body.budget.limit >= 0
        # Arithmetically consistent, because it comes from one ``consumed`` read.
        # Not ``consumed + remaining == limit``: since v0.13-s3.3 the counter is
        # reconciled against the requests really sent, so a retry storm can push
        # ``consumed`` past the cap — ``remaining`` floors at 0 and the sum stops
        # being the limit, which is the honest reading of an overshoot.
        assert body.budget.remaining == max(0, body.budget.limit - body.budget.consumed)
        # Null on purpose: counting quarantined rows is an O(attempted-rows)
        # scan and this endpoint is polled. The CLI's --status still reports it.
        assert body.quarantined is None
        assert response.json()["quarantined"] is None
        # Story 1.4 owns coverage/ETA; the control plane must not grow one.
        for forbidden in ("coverage", "eta_days", "throughput", "remaining_properties"):
            assert forbidden not in response.json()

    def test_start_is_accepted_as_a_request_not_an_execution(
        self, client, admin_headers, backfill_redis
    ):
        from api.schemas import BackfillStartResponse

        response = client.post("/admin/backfill/start", headers=admin_headers)
        assert response.status_code == 202, response.text[:300]
        body = BackfillStartResponse.model_validate(response.json())
        assert body.requested is True
        assert body.already_requested is False
        assert body.requested_at
        assert body.runner_present is False

        again = client.post("/admin/backfill/start", headers=admin_headers)
        assert again.status_code == 202
        repeat = BackfillStartResponse.model_validate(again.json())
        assert repeat.already_requested is True
        assert repeat.requested_at == body.requested_at

    def test_start_conflicts_with_a_held_lease(self, client, admin_headers, backfill_redis):
        prefix = get_config().backfill.redis_prefix
        backfill_redis.set(f"{prefix}:lease", "someone-elses-token")
        backfill_redis.hset(
            f"{prefix}:lease:meta",
            mapping={"token": "someone-elses-token", "owner": "host:4711"},
        )

        response = client.post("/admin/backfill/start", headers=admin_headers)

        assert response.status_code == 409
        assert "host:4711" in response.json()["detail"]
        assert f"{prefix}:control:start" not in backfill_redis.kv

    @pytest.mark.parametrize("action", ["pause", "resume"])
    def test_pause_and_resume_return_the_refreshed_status(
        self, client, admin_headers, backfill_redis, action
    ):
        from api.schemas import BackfillControlResponse

        response = client.post(f"/admin/backfill/{action}", headers=admin_headers)
        assert response.status_code == 200, response.text[:300]
        body = BackfillControlResponse.model_validate(response.json())
        assert body.action == action
        expected = ["pause"] if action == "pause" else []
        assert body.status is not None
        assert body.status.pending_requests == expected
        # ``cleared_start`` is part of the wire shape (pause withdraws a start
        # request that no run could ever honor); nothing was queued here.
        assert body.cleared_start is False
        assert "cleared_start" in response.json()

    def test_a_control_response_may_carry_a_null_status(self, client, admin_headers):
        """A null status means the mutation WAS applied and only the follow-up
        status read failed — story 1.6 must not render that as an error."""
        from api.schemas import BackfillControlResponse

        body = BackfillControlResponse.model_validate(
            {"action": "pause", "status": None}
        )
        assert body.status is None
        assert body.cleared_start is False

    def test_pause_withdraws_a_start_request_nothing_can_honor(
        self, client, admin_headers, backfill_redis
    ):
        from api.schemas import BackfillControlResponse

        started = client.post("/admin/backfill/start", headers=admin_headers)
        assert started.status_code == 202

        response = client.post("/admin/backfill/pause", headers=admin_headers)

        assert response.status_code == 200, response.text[:300]
        body = BackfillControlResponse.model_validate(response.json())
        assert body.cleared_start is True
        prefix = get_config().backfill.redis_prefix
        assert f"{prefix}:control:start" not in backfill_redis.kv


class TestAdminEnrichmentCoverageContract:
    """``/admin/enrichment/coverage``: auth gate first, then the DB-derived wire
    shape the Operações coverage card and the Painel health chip read.

    The runner's Redis is faked (no lease held), so this locks the contract for
    the "no run in progress" case — which is also the case where every
    projection field must be absent rather than zero."""

    _PATH = "/admin/enrichment/coverage"

    @pytest.fixture
    def backfill_redis(self, monkeypatch):
        fake = _FakeBackfillRedis()
        monkeypatch.setattr("api.admin.get_redis", lambda: fake)
        return fake

    def test_requires_admin_credentials(self, client):
        response = client.get(self._PATH)
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_rejects_an_invalid_credential(self, client):
        response = client.get(self._PATH, headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 403

    def test_matches_the_response_model(self, client, admin_headers, backfill_redis):
        from api.schemas import EnrichmentCoverageResponse
        from core.enrichment import EnrichmentTaskClass

        response = client.get(self._PATH, headers=admin_headers)
        _assert_ok_or_skip_infra(response, endpoint=f"GET {self._PATH}")
        body = EnrichmentCoverageResponse.model_validate(response.json())

        # One entry per task class, in enum order: a missing signal would read
        # as "not applicable" instead of "not enriched".
        assert [s.task_class for s in body.signals] == [
            tc.value for tc in EnrichmentTaskClass
        ]
        measured = []
        for signal in body.signals:
            assert signal.enriched >= 0
            assert signal.total == body.total_properties
            if signal.total == 0:
                # Absence over zero — undefined coverage is null on the wire.
                assert signal.fraction is None
            else:
                assert signal.fraction is not None
                assert 0.0 <= signal.fraction <= 1.0
                measured.append(signal.fraction)
        assert body.minimum_fraction == (min(measured) if measured else None)

        # No lease is held in the fake, so no projection may be stated.
        assert body.backfill.active is False
        assert body.backfill.remaining >= 0
        assert body.backfill.throughput_per_day is None
        assert body.backfill.eta_days is None
        assert body.backfill.projected_completion_date is None

    def test_repeated_calls_agree(self, client, admin_headers, backfill_redis):
        """AC: the figures are DB-derived, so an unchanged corpus reads the same."""
        first = client.get(self._PATH, headers=admin_headers)
        _assert_ok_or_skip_infra(first, endpoint=f"GET {self._PATH}")
        second = client.get(self._PATH, headers=admin_headers)
        assert second.status_code == 200
        assert first.json()["signals"] == second.json()["signals"]
