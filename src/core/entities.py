from pydantic import BaseModel, Field, validator, root_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re

class LocationData(BaseModel):
    """Location information for a property."""
    
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: str = Field(..., min_length=1)
    
    @validator('address')
    def validate_address(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Address cannot be empty')
        return v.strip()

class ListingInfo(BaseModel):
    """Information about a property listing."""
    
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[int] = Field(None, ge=0)
    area_sqm: Optional[int] = Field(None, ge=0)
    property_type: Optional[str] = None
    listing_type: Optional[str] = None
    
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()

class PropertyCandidate(BaseModel):
    """Validated scraper output.  All scrapers must produce this before DB persistence."""
    
    platform_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    location: LocationData
    listing_info: ListingInfo
    images: Optional[List[str]] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    @validator('platform_id')
    def coerce_platform_id(cls, v):
        if not isinstance(v, str):
            return str(v)
        return v.strip()
    
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()

class DedupeResult(BaseModel):
    """Result of deduplication process."""
    
    is_duplicate: bool
    confidence: float = Field(..., ge=0, le=1)
    matched_property_id: Optional[str] = None

class ScoringWeights(BaseModel):
    """Blending weights for statistical vs. AI scores."""
    
    ai_weight: float = Field(..., ge=0, le=1)
    statistical_weight: float = Field(..., ge=0, le=1)
    
    @validator('ai_weight', 'statistical_weight')
    def weights_must_sum_to_one(cls, v, info):
        if info.field_name == 'ai_weight':
            # Verificar se a soma dos pesos é 1.0
            if hasattr(info.data, 'statistical_weight'):
                total = v + info.data['statistical_weight']
                if abs(total - 1.0) > 0.001:
                    raise ValueError('Weights must sum to 1.0')
        return v

class VisualAnalysisResult(BaseModel):
    """Result of visual analysis."""
    
    tags: List[str] = []
    sentiment: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0, le=1)

class SentimentAnalysisResult(BaseModel):
    """Result of sentiment analysis."""
    
    sentiment: str = Field(..., regex=r'^(positive|negative|neutral)$')
    confidence: float = Field(..., ge=0, le=1)
    text: str = Field(..., min_length=1)
