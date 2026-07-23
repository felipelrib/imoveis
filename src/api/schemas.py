from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class PropertyListingModel(BaseModel):
    platform: str
    platform_listing_id: str
    listing_type: str
    price: float
    currency: str
    url: str
    is_furnished: Optional[bool] = None
    accepts_pets: Optional[bool] = None
    condo_fee: Optional[float] = None
    iptu: Optional[float] = None


class PropertyModel(BaseModel):
    id: str
    platform: str
    platform_id: str
    title: str
    price: float
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    address: Optional[str] = None
    image_urls: List[str]
    created_at: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    stat_score: Optional[float] = None
    ai_score: Optional[float] = None
    combined_score: Optional[float] = None
    percentile_rank: Optional[float] = None
    z_score: Optional[float] = None
    price_per_m2: Optional[float] = None
    neighborhood_mean: Optional[float] = None
    neighborhood_id: Optional[str] = None
    neighborhood_name: Optional[str] = None
    parking: Optional[int] = None
    description: Optional[str] = None
    available_for_rent: bool = False
    available_for_sale: bool = False
    ai_features: List[str] = []
    ai_issues: List[str] = []
    ai_green_flags: List[str] = []
    ai_red_flags: List[str] = []
    condition_score: Optional[int] = None
    sentiment_score: Optional[int] = None
    stat_category: Optional[str] = None
    stat_reasoning: Optional[str] = None
    deal_summary: Optional[str] = None
    visual_category: Optional[str] = None
    visual_reasoning: Optional[str] = None
    sentiment_category: Optional[str] = None
    sentiment_reasoning: Optional[str] = None
    listings: List[PropertyListingModel] = []
    primary_listing: Optional[PropertyListingModel] = None
    model_config = ConfigDict(extra="ignore")


class PaginatedPropertiesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    properties: List[PropertyModel]


class PropertyBatchResponse(BaseModel):
    properties: List[PropertyModel]


class PropertyExportResponse(BaseModel):
    """JSON export envelope for ``GET /properties/export?format=json`` (BIN-50)."""

    properties: List[PropertyModel]
    total: int
    truncated: bool


class NeighborhoodModel(BaseModel):
    name: str
    count: int


class PropertyDetailModel(BaseModel):
    id: str
    platform: str
    platform_id: str
    title: str
    description: Optional[str] = None
    price: float
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking: Optional[int] = None
    address: Optional[str] = None
    image_urls: List[str]
    created_at: Optional[str] = None
    props_json: Dict[str, Any]
    stat_score: Optional[float] = None
    ai_score: Optional[float] = None
    combined_score: Optional[float] = None
    percentile_rank: Optional[float] = None
    z_score: Optional[float] = None
    price_per_m2: Optional[float] = None
    neighborhood_mean: Optional[float] = None
    neighborhood_median: Optional[float] = None
    neighborhood_id: Optional[str] = None
    neighborhood_name: Optional[str] = None
    location: Dict[str, Any]
    listings: List[PropertyListingModel] = []
    primary_listing: Optional[PropertyListingModel] = None
    deal_summary: Optional[str] = None
    stat_analysis: Dict[str, Any]
    ai_analysis: Dict[str, Any]
    model_config = ConfigDict(extra="ignore")


class PriceHistoryModel(BaseModel):
    id: str
    price: float
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    listing_type: str
    platform: str
    property_listing_id: Optional[str] = None


# System models
class SystemStatusResponse(BaseModel):
    database: Dict[str, Any]
    redis: Dict[str, Any]
    ollama: Dict[str, Any]
    workers: Dict[str, Any]
    ai_workers_paused: bool
    stats: Dict[str, Any]


class PipelineResponse(BaseModel):
    queues: Dict[str, int]
    scrapers_status: Dict[str, Any]
    ai_metrics: Dict[str, Any]
