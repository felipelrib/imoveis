from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()

class Neighborhood(Base):
    __tablename__ = 'neighborhoods'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, index=True)
    city = Column(String(255), nullable=False, index=True)
    state = Column(String(100), nullable=False, index=True)
    country = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)

class Property(Base):
    __tablename__ = 'properties'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_id = Column(String(255), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False, index=True)
    address = Column(String(500), nullable=False)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    area_sqm = Column(Integer)
    property_type = Column(String(100))
    listing_type = Column(String(50))
    created_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)
    
    # Índices otimizados para consultas frequentes
    __table_args__ = (
        Index('idx_properties_price', 'price'),
        Index('idx_properties_location', 'latitude', 'longitude'),
        Index('idx_properties_created_at', 'created_at'),
        Index('idx_properties_platform_id', 'platform_id'),
    )

class PropertyListing(Base):
    __tablename__ = 'property_listings'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    platform_id = Column(String(255), nullable=False, index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False, index=True)
    address = Column(String(500), nullable=False)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    area_sqm = Column(Integer)
    property_type = Column(String(100))
    listing_type = Column(String(50))
    created_at = Column(DateTime, nullable=False, index=True)
    updated_at = Column(DateTime, nullable=False)

class PriceHistory(Base):
    __tablename__ = 'price_history'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    price = Column(Float, nullable=False)
    date = Column(DateTime, nullable=False, index=True)
    source = Column(String(100))

class PlatformConfig(Base):
    __tablename__ = 'platform_configs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform_name = Column(String(100), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=True)
    config_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

class MetricsScoring(Base):
    __tablename__ = 'metrics_scoring'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    ai_score = Column(Float)
    statistical_score = Column(Float)
    combined_score = Column(Float, nullable=False, index=True)
    weights = Column(JSON)
    created_at = Column(DateTime, nullable=False, index=True)
