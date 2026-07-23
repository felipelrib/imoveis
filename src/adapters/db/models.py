import sqlalchemy as sa
from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

SQL_GEN_RANDOM_UUID = "gen_random_uuid()"
SQL_NOW = "now()"
FK_PROPERTIES_ID = "properties.id"


class GPUControl(Base):
    __tablename__ = "gpu_control"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    name = Column(String, unique=True, nullable=False)
    value = Column(JSON)
    updated_at = Column(DateTime, server_default=sa.text(SQL_NOW), onupdate=sa.text(SQL_NOW))


class Neighborhood(Base):
    __tablename__ = "neighborhoods"
    __table_args__ = (
        sa.UniqueConstraint("name", "city", "state", name="uq_neighborhoods_name_city_state"),
    )
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    name = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String(2), nullable=False)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326))
    created_at = Column(DateTime, server_default=sa.text(SQL_NOW))


class PlatformCheckpoint(Base):
    __tablename__ = "platform_checkpoints"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    platform_name = Column(String, unique=True, nullable=False)
    data = Column(JSON)
    updated_at = Column(DateTime, server_default=sa.text(SQL_NOW), onupdate=sa.text(SQL_NOW))


class PlatformConfig(Base):
    __tablename__ = "platform_configs"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    platform_name = Column(String, unique=True)
    base_url = Column(String)
    enabled = Column(Boolean)
    rate_limit = Column(Integer)
    jitter_min = Column(Integer)
    jitter_max = Column(Integer)
    extra = Column(JSON)


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (sa.UniqueConstraint("platform", "platform_id", name="uq_property_platform_id"),)
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    platform = Column(String, nullable=False)
    platform_id = Column(String, nullable=False, index=True)
    title = Column(String)
    description = Column(String)
    price = Column(Float, nullable=False)
    currency = Column(String(3))
    area_m2 = Column(Float)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    parking = Column(Integer)
    location = Column(Geometry(geometry_type="POINT", srid=4326))
    address = Column(String)
    image_urls = Column(JSON)
    props_json = Column(JSON)
    first_seen = Column(DateTime, server_default=sa.text(SQL_NOW))
    last_updated = Column(DateTime, server_default=sa.text(SQL_NOW), onupdate=sa.text(SQL_NOW))
    active = Column(Boolean, server_default=sa.text("true"))
    neighborhood_id = Column(UUID(as_uuid=True), ForeignKey("neighborhoods.id"), index=True)
    # nomic-embed-text (Ollama) produces 768-d vectors for semantic search
    embedding = Column(Vector(768), nullable=True)


class MetricsScoring(Base):
    __tablename__ = "metrics_scoring"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    property_id = Column(UUID(as_uuid=True), ForeignKey(FK_PROPERTIES_ID, ondelete="CASCADE"))
    stat_score = Column(Float)
    ai_score = Column(Float)
    combined_score = Column(Float)
    percentile_rank = Column(Float)
    z_score = Column(Float)
    price_per_m2 = Column(Float)
    neighborhood_mean = Column(Float)
    neighborhood_median = Column(Float)
    meta = Column(JSON)
    updated_at = Column(DateTime, server_default=sa.text(SQL_NOW), onupdate=sa.text(SQL_NOW))


class PriceHistory(Base):
    __tablename__ = "price_history"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    property_id = Column(UUID(as_uuid=True), ForeignKey(FK_PROPERTIES_ID, ondelete="CASCADE"))
    listing_type = Column(String, nullable=False, default="sale")  # 'rent' or 'sale'
    platform = Column(String, nullable=True)
    property_listing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("property_listings.id", ondelete="SET NULL"),
        nullable=True,
    )
    price = Column(Float, nullable=False)
    start_ts = Column(DateTime, server_default=sa.text(SQL_NOW))
    end_ts = Column(DateTime)


class PropertyListing(Base):
    __tablename__ = "property_listings"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_PROPERTIES_ID, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform = Column(String, nullable=False)
    platform_listing_id = Column(String, nullable=False)
    listing_type = Column(String, nullable=False)  # 'rent' or 'sale'
    price = Column(Float, nullable=False)
    currency = Column(String(3))
    url = Column(String)
    is_furnished = Column(Boolean)
    accepts_pets = Column(Boolean)
    condo_fee = Column(Float)
    iptu = Column(Float)
    raw_json = Column(JSON)
    first_seen = Column(DateTime, server_default=sa.text(SQL_NOW))
    last_seen = Column(DateTime, server_default=sa.text(SQL_NOW), onupdate=sa.text(SQL_NOW))
    active = Column(Boolean, server_default=sa.text("true"))

    __table_args__ = (
        sa.UniqueConstraint(
            "platform",
            "platform_listing_id",
            "listing_type",
            name="uq_platform_listing",
        ),
    )


class Watchlist(Base):
    """Track properties the user wants price-drop alerts for."""

    __tablename__ = "watchlist"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_PROPERTIES_ID, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String, nullable=True)
    min_drop_pct = Column(Float, default=5.0, nullable=False)
    last_notified_price = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=sa.text(SQL_NOW))

    __table_args__ = (
        sa.UniqueConstraint("property_id", name="uq_watchlist_property"),
    )


class SavedSearch(Base):
    """Persist filter sets so users can reapply them later."""

    __tablename__ = "saved_searches"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    name = Column(String, nullable=False)
    filters = Column(sa.JSON, nullable=False)
    owner = Column(UUID(as_uuid=True), nullable=True)  # for future auth
    created_at = Column(DateTime, server_default=sa.text(SQL_NOW))


class Favourite(Base):
    """Track properties the user has favourited for quick access."""

    __tablename__ = "favourites"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    property_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_PROPERTIES_ID, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner = Column(UUID(as_uuid=True), nullable=True)  # for future auth
    created_at = Column(DateTime, server_default=sa.text(SQL_NOW))

    __table_args__ = (
        sa.UniqueConstraint("property_id", name="uq_favourite_property"),
    )


class AdminAudit(Base):
    """Log of actions performed by administrators."""

    __tablename__ = "admin_audit"
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text(SQL_GEN_RANDOM_UUID),
    )
    action = Column(String, nullable=False)
    payload = Column(sa.JSON, nullable=True)
    performed_at = Column(DateTime, server_default=sa.text(SQL_NOW))


# --- ORM Event Hooks ---

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import event  # noqa: E402


@event.listens_for(Property, "after_delete")
def delete_property_images(mapper, connection, target):
    import structlog

    from infra.config import get_config
    logger = structlog.get_logger()
    base = get_config().image_storage_path
    if not base:
        return
    image_dir = Path(base) / str(target.id)
    if image_dir.exists():
        try:
            shutil.rmtree(image_dir, ignore_errors=True)
            logger.info("property_images_deleted", property_id=str(target.id))
        except Exception as exc:
            logger.warning("property_images_delete_failed", property_id=str(target.id), error=str(exc))
