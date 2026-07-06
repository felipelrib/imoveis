"""Pydantic domain models — framework-agnostic validation layer.

These models sit between the scrapers (raw data) and the persistence
layer (SQLAlchemy).  Every scraper must produce a ``PropertyCandidate``
before data can be written to the database.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class LocationData(BaseModel):
    """WGS-84 coordinate pair."""
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


# ---------------------------------------------------------------------------
# Scraper → DB bridge
# ---------------------------------------------------------------------------

class ListingInfo(BaseModel):
    """Specific listing on a platform for rent or sale."""
    platform: str
    platform_id: str
    listing_type: str  # 'rent' or 'sale'
    price: float
    url: str

class PropertyCandidate(BaseModel):
    """Validated scraper output.  All scrapers must produce this before DB persistence."""

    platform: str
    platform_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    area_m2: Optional[float] = Field(None, gt=0)
    bedrooms: Optional[int] = Field(None, ge=0)
    bathrooms: Optional[int] = Field(None, ge=0)
    parking: Optional[int] = Field(None, ge=0)
    location: LocationData
    address: Optional[str] = None
    image_urls: List[str] = Field(default_factory=list)
    props_json: Dict[str, Any] = Field(default_factory=dict)
    listings: List[ListingInfo] = Field(default_factory=list)

    @field_validator('platform_id', mode='before')
    @classmethod
    def coerce_platform_id(cls, v: Any) -> str:
        return str(v) if v is not None else v


# ---------------------------------------------------------------------------
# Deduplication result
# ---------------------------------------------------------------------------

class DedupeResult(BaseModel):
    """Outcome of the match-or-create deduplication step."""
    action: str  # 'created' | 'updated' | 'noop'
    property_id: str
    is_duplicate: bool = False
    matched_property_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class ScoringWeights(BaseModel):
    """Blending weights for statistical vs. AI scores."""
    stat_weight: float = Field(0.5, ge=0, le=1)
    ai_weight: float = Field(0.5, ge=0, le=1)

    @field_validator('ai_weight', mode='before')
    @classmethod
    def weights_must_sum_to_one(cls, v: Any, info: Any) -> Any:
        # Just validate range; they don't have to sum to exactly 1.0
        return v


# ---------------------------------------------------------------------------
# AI analysis results
# ---------------------------------------------------------------------------

class VisualAnalysisResult(BaseModel):
    """Output of the VLM visual-quality scorer."""
    condition_score: float = Field(0.5, ge=0, le=1)
    features_detected: List[str] = Field(default_factory=list)
    issues_detected: List[str] = Field(default_factory=list)
    raw_response: str = ""


class SentimentAnalysisResult(BaseModel):
    """Output of the LLM description-sentiment analyser."""
    sentiment_score: float = Field(0.5, ge=0, le=1)
    green_flags: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    raw_response: str = ""
