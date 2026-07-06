from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, Float, UUID, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

Base = declarative_base()

class Neighborhood(Base):
    __tablename__ = 'neighborhoods'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Property(Base):
    __tablename__ = 'properties'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    platform_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    price = Column(Float)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    parking_spaces = Column(Integer)
    area = Column(Float)
    address = Column(String)
    neighborhood_id = Column(UUID, ForeignKey('neighborhoods.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PropertyListing(Base):
    __tablename__ = 'property_listings'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID, ForeignKey('properties.id'))
    platform = Column(String, nullable=False)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class PriceHistory(Base):
    __tablename__ = 'price_history'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID, ForeignKey('properties.id'))
    price = Column(Float, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)

class PlatformConfig(Base):
    __tablename__ = 'platform_configs'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    platform_name = Column(String, nullable=False, unique=True)
    config = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class MetricsScoring(Base):
    __tablename__ = 'metrics_scoring'
    
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    property_id = Column(UUID, ForeignKey('properties.id'))
    ai_score = Column(Float)
    statistical_score = Column(Float)
    combined_score = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
