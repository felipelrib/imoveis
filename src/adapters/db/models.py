"""SQLAlchemy ORM models for the real-estate backend.

Models:
    Neighborhood  — geographic boundary polygons for neighbourhood lookup
    Property      — scraped listing with PostGIS POINT location
    PriceHistory  — SCD-2 price changes per property
    PlatformConfig — per-platform scraper configuration
    MetricsScoring — statistical + AI scoring per property
"""
from sqlalchemy import (
    Column, Integer, String, Float, JSON, Boolean, DateTime,
    ForeignKey, UniqueConstraint, func, Enum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
import sqlalchemy as sa

Base = declarative_base()


# ---------------------------------------------------------------------------
# Neighborhood
# ---------------------------------------------------------------------------

class Neighborhood(Base):
    __tablename__ = 'neighborhoods'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    name = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String(2), nullable=False)
    geometry = Column(Geometry(geometry_type='POLYGON', srid=4326))
    created_at = Column(DateTime, server_default=func.now())

    # relationships
    properties = relationship('Property', back_populates='neighborhood')


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

class Property(Base):
    __tablename__ = 'properties'
    __table_args__ = (
        UniqueConstraint('platform', 'platform_id', name='uq_platform_platform_id'),
        {'comment': 'Spatial index on location column managed by GeoAlchemy2'},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    platform = Column(String, nullable=False)
    platform_id = Column(String, nullable=False, index=True)
    title = Column(String)
    description = Column(String)
    price = Column(Float, nullable=False)
    currency = Column(String(3), default='BRL')
    area_m2 = Column(Float)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    parking = Column(Integer)
    location = Column(Geometry(geometry_type='POINT', srid=4326))
    address = Column(String)
    image_urls = Column(JSON, default=list)
    props_json = Column(JSON)
    first_seen = Column(DateTime, server_default=func.now())
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    active = Column(Boolean, default=True)
    neighborhood_id = Column(
        UUID(as_uuid=True),
        ForeignKey('neighborhoods.id'),
        nullable=True,
        index=True,
    )

    # relationships
    price_history = relationship(
        'PriceHistory', back_populates='property',
        cascade='all, delete-orphan',
    )
    scoring = relationship(
        'MetricsScoring', back_populates='property',
        uselist=False, cascade='all, delete-orphan',
    )
    neighborhood = relationship('Neighborhood', back_populates='properties')
    listings = relationship(
        'PropertyListing', back_populates='property',
        cascade='all, delete-orphan',
    )


# ---------------------------------------------------------------------------
# PropertyListing
# ---------------------------------------------------------------------------

class PropertyListing(Base):
    __tablename__ = 'property_listings'
    __table_args__ = (
        UniqueConstraint('platform', 'platform_id', 'listing_type', name='uq_platform_id_type'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    property_id = Column(UUID(as_uuid=True), ForeignKey('properties.id', ondelete='CASCADE'), nullable=False, index=True)
    platform = Column(String, nullable=False, index=True)
    platform_id = Column(String, nullable=False, index=True)
    listing_type = Column(String, nullable=False) # 'rent' or 'sale'
    price = Column(Float, nullable=False)
    url = Column(String)
    discovered_at = Column(DateTime, server_default=func.now())
    last_seen_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # relationships
    property = relationship('Property', back_populates='listings')


# ---------------------------------------------------------------------------
# PriceHistory
# ---------------------------------------------------------------------------

class PriceHistory(Base):
    __tablename__ = 'price_history'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    property_id = Column(UUID(as_uuid=True), ForeignKey('properties.id', ondelete='CASCADE'))
    price = Column(Float, nullable=False)
    start_ts = Column(DateTime, server_default=func.now())
    end_ts = Column(DateTime, nullable=True)

    # relationships
    property = relationship('Property', back_populates='price_history')


# ---------------------------------------------------------------------------
# PlatformConfig
# ---------------------------------------------------------------------------

class PlatformConfig(Base):
    __tablename__ = 'platform_configs'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    platform_name = Column(String, unique=True)
    base_url = Column(String)
    enabled = Column(Boolean, default=True)
    rate_limit = Column(Integer, default=30)
    jitter_min = Column(Integer, default=2)
    jitter_max = Column(Integer, default=7)
    extra = Column(JSON)


# ---------------------------------------------------------------------------
# MetricsScoring
# ---------------------------------------------------------------------------

class MetricsScoring(Base):
    __tablename__ = 'metrics_scoring'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    property_id = Column(UUID(as_uuid=True), ForeignKey('properties.id', ondelete='CASCADE'))
    stat_score = Column(Float)
    ai_score = Column(Float)
    combined_score = Column(Float)
    percentile_rank = Column(Float)
    z_score = Column(Float)
    price_per_m2 = Column(Float)
    neighborhood_mean = Column(Float)
    neighborhood_median = Column(Float)
    meta = Column(JSON)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # relationships
    property = relationship('Property', back_populates='scoring')
