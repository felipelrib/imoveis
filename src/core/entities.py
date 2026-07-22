from typing import List, Optional

from pydantic import BaseModel, field_validator, model_validator


class LocationData(BaseModel):
    """Location information for a property."""

    address: str
    neighborhood: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float

    @field_validator("address")
    @classmethod
    def validate_address(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Address cannot be empty")
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

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("Title cannot be empty")
        return v.strip()


class PropertyCandidate(BaseModel):
    """Validated scraper output.  All scrapers must produce this before DB persistence."""

    platform: str
    platform_id: str
    title: Optional[str] = None
    description: Optional[str] = ""
    price: float
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking: Optional[int] = None
    location: Optional[dict] = None  # {"lat": float, "lon": float}
    address: Optional[str] = None
    image_urls: Optional[List[str]] = []
    props_json: Optional[dict] = None
    listings: Optional[List[dict]] = None
    currency: Optional[str] = "BRL"

    @field_validator("platform_id")
    @classmethod
    def coerce_platform_id(cls, v):
        if not v:
            raise ValueError("Platform ID cannot be empty")
        return str(v)

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError("Price must be positive")
        return v


class DedupeResult(BaseModel):
    """Result of deduplication process."""

    is_duplicate: bool
    matched_property_id: Optional[str] = None


class ScoringWeights(BaseModel):
    """Blending weights for statistical vs. AI scores."""

    ai_weight: float = 0.5
    stat_weight: float = 0.5

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> 'ScoringWeights':
        return self


class VisualAnalysisResult(BaseModel):
    """Result of visual analysis (image processing)."""

    sentiment: str
    features: List[str] = []
    confidence: float = 0.0


class SentimentAnalysisResult(BaseModel):
    """Result of sentiment analysis."""

    sentiment: str
    confidence: float = 0.0
