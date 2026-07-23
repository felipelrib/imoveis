from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Any, Optional
from datetime import datetime

class PropertyListingModel(BaseModel):
    platform: str
    platform_listing_id: str
    listing_type: str
    price: float
    currency: str
    url: str
    is_furnished: Optional[bool]
    accepts_pets: Optional[bool]
    condo_fee: Optional[float]
    iptu: Optional[float]

class PropertyModel(BaseModel):
    id: str
    platform: str
    platform_id: str
    title: str
    price: float
    area_m2: Optional[float]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    address: Optional[str]
    image_urls: List[str]
    created_at: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    stat_score: Optional[float]
    ai_score: Optional[float]
    combined_score: Optional[float]
    percentile_rank: Optional[float]
    z_score: Optional[float]
    price_per_m2: Optional[float]
    neighborhood_mean: Optional[float]
    neighborhood_name: Optional[str]
    parking: Optional[int]
    description: Optional[str]
    available_for_rent: bool = False
    available_for_sale: bool = False
    ai_features: List[str] = []
    ai_issues: List[str] = []
    ai_green_flags: List[str] = []
    ai_red_flags: List[str] = []
    condition_score: Optional[int]
    sentiment_score: Optional[int]
    stat_category: Optional[str]
    stat_reasoning: Optional[str]
    deal_summary: Optional[str]
    visual_category: Optional[str]
    visual_reasoning: Optional[str]
    sentiment_category: Optional[str]
    sentiment_reasoning: Optional[str]
    listings: List[PropertyListingModel] = []
    model_config = ConfigDict(extra='ignore')

class PaginatedPropertiesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    properties: List[PropertyModel]

class NeighborhoodModel(BaseModel):
    name: str
    count: int

class PropertyDetailModel(BaseModel):
    id: str
    platform: str
    platform_id: str
    title: str
    description: Optional[str]
    price: float
    area_m2: Optional[float]
    bedrooms: Optional[int]
    bathrooms: Optional[int]
    parking: Optional[int]
    address: Optional[str]
    image_urls: List[str]
    created_at: Optional[str]
    props_json: Dict[str, Any]
    stat_score: Optional[float]
    ai_score: Optional[float]
    combined_score: Optional[float]
    percentile_rank: Optional[float]
    z_score: Optional[float]
    price_per_m2: Optional[float]
    neighborhood_mean: Optional[float]
    neighborhood_median: Optional[float]
    neighborhood_name: Optional[str]
    location: Dict[str, Any]
    listings: List[PropertyListingModel] = []
    deal_summary: Optional[str]
    stat_analysis: Dict[str, Any]
    ai_analysis: Dict[str, Any]
    model_config = ConfigDict(extra='ignore')

class PriceHistoryModel(BaseModel):
    id: str
    price: float
    start_ts: Optional[str]
    end_ts: Optional[str]
    listing_type: str
    platform: str
    property_listing_id: Optional[str]

# System models
class SystemStatusResponse(BaseModel):
    database: Dict[str, Any]
    redis: Dict[str, Any]
    ollama: Dict[str, Any]
    ai_workers_paused: bool
    stats: Dict[str, Any]

class PipelineResponse(BaseModel):
    queues: Dict[str, int]
    scrapers_status: Dict[str, Any]
    ai_metrics: Dict[str, Any]
