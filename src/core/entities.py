from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime

class LocationData(BaseModel):
    """Location information for a property."""

    address: str
    neighborhood: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float

    @validator('address')
    def validate_address(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Address cannot be empty')
        return v.strip()

class ListingInfo(BaseModel):
    """Information about a property listing."""

    title: str
    description: str
    url: str
    price: float
    bedrooms: int
    bathrooms: int
    parking_spaces: int
    area: float

    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()

class PropertyCandidate(BaseModel):
    """Validated scraper output.  All scrapers must produce this before DB persistence."""

    platform_id: str
    title: str
    description: str
    price: float
    bedrooms: int
    bathrooms: int
    parking_spaces: int
    area: float
    address: str
    neighborhood: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float
    url: str
    platform: str
    images: List[str] = []
    created_at: datetime

    @validator('platform_id')
    def coerce_platform_id(cls, v):
        if not v:
            raise ValueError('Platform ID cannot be empty')
        return str(v)

    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Title cannot be empty')
        return v.strip()

class DedupeResult(BaseModel):
    """Result of deduplication process."""

    is_duplicate: bool
    matched_property_id: Optional[str] = None

class ScoringWeights(BaseModel):
    """Blending weights for statistical vs. AI scores."""

    ai_weight: float = 0.5
    statistical_weight: float = 0.5

    @validator('ai_weight', 'statistical_weight')
    def weights_must_sum_to_one(cls, v, info):
        if info.field_name == 'ai_weight':
            # Validate that the sum of both weights is 1.0
            other_weight = getattr(cls, 'statistical_weight', 0)
            if abs(v + other_weight - 1.0) > 0.001:
                raise ValueError('Weights must sum to 1.0')
        return v

class VisualAnalysisResult(BaseModel):
    """Result of visual analysis (image processing)."""

    sentiment: str
    features: List[str] = []
    confidence: float = 0.0

class SentimentAnalysisResult(BaseModel):
    """Result of sentiment analysis."""

    sentiment: str
    confidence: float = 0.0
