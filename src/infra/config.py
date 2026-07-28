"""Application configuration from YAML + env overrides (Pydantic v2).
Load the YAML config file, merge environment-variable overrides, validate the
resulting dict against a Pydantic schema, and expose a frozen typed
``AppConfig`` singleton.

Usage::

    from src.infra.config import get_config

    cfg = get_config()
    engine = create_async_engine(cfg.database.url)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field

from src.core.exceptions import ConfigError

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent  # src/infra/
_REPO_ROOT = _HERE.parent.parent  # repo root
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "app_config.yaml"

# Prefix for environment variable overrides
_ENV_PREFIX = "IMOVEIS_"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AppSettings(BaseModel, frozen=True):
    """Top-level application metadata and runtime knobs."""

    name: str = "imoveis"
    version: str = "0.1.0"
    debug: bool = False
    api_port: int = 8000
    log_level: str = "INFO"


class DatabaseConfig(BaseModel, frozen=True):
    """PostgreSQL / PostGIS connection settings.

    Individual fields are the primary representation.  The ``url`` property
    reconstructs a SQLAlchemy-compatible connection string from them.  If the
    ``DATABASE_URL`` environment variable is set it will override these fields.
    """

    host: str = "localhost"
    port: int = 5432
    name: str = "imoveis"
    user: str = "imoveis"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 5
    pool_timeout: int = 30
    pool_pre_ping: bool = True

    @property
    def url(self) -> str:
        """Compute a SQLAlchemy connection string from individual fields."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseModel, frozen=True):
    """Redis connection settings.

    Like ``DatabaseConfig``, individual fields are the primary source.  A
    ``url`` property is provided for convenience.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class CeleryConfig(BaseModel, frozen=True):
    """Celery worker and beat settings."""

    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = Field(default_factory=lambda: ["json"])
    timezone: str = "America/Sao_Paulo"
    beat_schedule: dict[str, Any] = Field(default_factory=dict)


class GPUConfig(BaseModel, frozen=True):
    """GPU resource management."""

    enabled: bool = True
    semaphore_limit: int = 2


class AIConfig(BaseModel, frozen=True):
    """AI / VLM settings.

    Read from the ``ai:`` section of ``app_config.yaml``.  Individual model
    names can be overridden via ``AI_MODEL`` (visual) and ``AI_TEXT_MODEL``
    (text) environment variables.
    """

    backend: str = "ollama"  # ollama | lmstudio
    ollama_url: str = "http://localhost:11434"
    lmstudio_url: str = "http://localhost:1234"
    visual_model: str = "qwen2.5vl:7b"
    text_model: str = "qwen2.5vl:7b"
    embedding_model: str = "bge-m3"
    timeout: int = 120
    max_tokens: int = 1024
    num_ctx: int = 16384
    visual_weight: float = 0.7
    text_weight: float = 0.3
    max_images_per_property: int = 8
    max_description_chars: int = 1000
    output_language: str = "en"


class PlatformConfig(BaseModel, frozen=True):
    """Settings for a single real-estate scraping platform."""

    enabled: bool = True
    base_url: str = ""
    listing_selector: str = ""
    pagination_strategy: str = ""
    scrape_interval: int = 60  # minutes between scheduled scrapes (0 = manual only)
    rate_limit: int = 30  # requests per minute
    jitter_min: float = 2.0  # minimum delay between requests (seconds)
    jitter_max: float = 6.0  # maximum delay between requests (seconds)
    extra: dict[str, Any] = Field(default_factory=dict)  # platform-specific extras


class GeoAllowlistConfig(BaseModel, frozen=True):
    """Post-scrape city/state gate (BIN-68). Empty lists disable that axis."""

    enabled: bool = True
    cities: list[str] = Field(
        default_factory=lambda: ["Belo Horizonte", "São Paulo", "Campinas"]
    )
    states: list[str] = Field(default_factory=lambda: ["MG", "SP"])


class PhotoGateConfig(BaseModel, frozen=True):
    """Minimum gallery size for AI-eligible / deal-feed listings (BIN-78).

    Effective minimum is ``max(floor_min, ceil(max_images_per_property *
    coverage_ratio))`` unless ``min_photos`` is set (hard override).
    Under-threshold rows are persisted inactive for offline stats, not deleted.
    """

    enabled: bool = True
    floor_min: int = 8
    coverage_ratio: float = 1.0
    # None → use dynamic formula; set to force a fixed threshold.
    min_photos: int | None = None


class AvailabilityRecheckConfig(BaseModel, frozen=True):
    """Periodic URL recheck to soft-deactivate dead listings (BIN-80).

    Rows stay in the DB for history/stats; Properties API only surfaces
    ``active=true`` listings. Property rows flip inactive only when no active
    listings remain.
    """

    enabled: bool = True
    interval_minutes: int = 360
    batch_size: int = 50
    stale_after_hours: int = 24
    request_timeout_sec: float = 20.0


class ScrapingConfig(BaseModel, frozen=True):
    """Web scraping defaults and per-platform overrides."""

    default_delay: float = 2.0
    user_agent: str = "imoveis-bot/0.1 (real-estate-research)"
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)
    geo_allowlist: GeoAllowlistConfig = Field(default_factory=GeoAllowlistConfig)
    photo_gate: PhotoGateConfig = Field(default_factory=PhotoGateConfig)
    availability_recheck: AvailabilityRecheckConfig = Field(
        default_factory=AvailabilityRecheckConfig
    )


class FeaturesConfig(BaseModel, frozen=True):
    """Feature flags for optional functionality."""

    property_enrichment: bool = False
    price_alerts: bool = False


class ScoringConfig(BaseModel, frozen=True):
    """Scoring defaults and weights."""

    stat_weight: float = 0.4
    ai_weight: float = 0.4
    neighbourhood_weight: float = 0.2
    recalculate_on_enrichment: bool = True


class TopDealsDigestConfig(BaseModel, frozen=True):
    """Scheduled top-new-deals digest (BIN-52 / FR-21). Distinct from price-drop digest_mode."""

    enabled: bool = False
    limit: int = 10
    min_combined_score: float = 0.0
    lookback_hours: int = 168  # 7 days
    crontab_hour: int = 8
    crontab_minute: int = 0
    crontab_day_of_week: str = "0"  # Sunday (Celery crontab)
    redis_key: str = "alerts:top_deals_digest"


class AlertsConfig(BaseModel, frozen=True):
    """Price-drop alert settings."""

    enabled: bool = True
    channels: list[str] = Field(default_factory=lambda: ["log"])
    redis_key: str = "alerts:price_drops"
    redis_ttl_seconds: int = 604800   # 7 days
    redis_max_items: int = 200
    min_drop_pct_default: float = 5.0
    digest_mode: bool = False
    digest_email: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_pass: str = ""
    top_deals: TopDealsDigestConfig = Field(default_factory=TopDealsDigestConfig)


class AuthConfig(BaseModel, frozen=True):
    """API edge credential and JWT settings (AD-2 / AD-6 / AD-11).

    Secrets are empty by default — supply via env (``API_KEY``, ``JWT_SECRET``,
    ``ADMIN_USER``, ``ADMIN_PASS``, or ``IMOVEIS_AUTH__*``). Never commit real
    credentials in YAML samples.
    """

    api_key: str = ""
    jwt_secret: str = ""
    principal_id: str = "default"
    admin_user: str = "admin"
    admin_pass: str = "admin"


class UiConfig(BaseModel, frozen=True):
    """Operator UI locale defaults (BIN-98 / product i18n).

    Active locale (Redis ``ui:locale`` → ``ui.locale``) drives SPA chrome and
    new AI free-text generation (BIN-101). ``ai.output_language`` remains a
    config fallback when the UI locale resolver is unavailable. YAML remains
    the install default.
    """

    locale: Literal["en", "pt-BR"] = "en"
    supported_locales: list[str] = Field(default_factory=lambda: ["en", "pt-BR"])


class ProxyConfig(BaseModel, frozen=True):
    """HTTP proxy pool settings for scrapers (AD-2 / FR-20).

    Loaded from the ``proxy:`` block in ``app_config.yaml``. Credentials belong
    in env / local overrides — never commit real proxy URLs with passwords in
    sample config.
    """

    enabled: bool = False
    url: str | None = None
    rotation_strategy: Literal["round_robin", "random"] = "round_robin"
    pool: list[str] = Field(default_factory=list)


class DedupConfig(BaseModel, frozen=True):
    """Deduplication thresholds loaded from the ``dedup:`` YAML block.

    Consumed by ``tasks.scrape_listings`` when matching scraped candidates
    against existing properties.
    """

    radius_m: float = 50.0
    area_tolerance_m2: float = 2.0
    text_similarity_threshold: float = 0.65
    text_similarity_algorithm: str = "jaro_winkler"


class PipelineMetricsConfig(BaseModel, frozen=True):
    """Server-side pipeline metric snapshots for Dashboard history (BIN-61)."""

    snapshot_interval_sec: float = 30.0
    retention_days: int = 7


class OsmAmenitiesConfig(BaseModel, frozen=True):
    """OSM amenity density refresh for neighbourhood profiles (BIN-88).

    ``mode=geojson`` loads an offline POI FeatureCollection (preferred for
    CI/dev). ``mode=overpass`` queries Overpass HTTP with rate limiting.
    Default ``enabled=false`` so beat does not hit Overpass until configured.
    """

    enabled: bool = False
    mode: str = "geojson"  # geojson | overpass
    poi_geojson_path: str = ""
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    request_timeout_sec: float = 60.0
    rate_limit_per_minute: float = 8.0
    buffer_m: float = 0.0
    cache_dir: str = ""
    cache_ttl_hours: float = 24.0
    interval_hours: float = 168.0
    batch_size: int = 50
    category_targets: dict[str, float] = Field(
        default_factory=lambda: {
            "shop": 3.0,
            "park": 1.0,
            "school": 1.0,
            "healthcare": 2.0,
        }
    )


class AccessHubConfig(BaseModel, frozen=True):
    """A fixed downtown / life hub used for neighbourhood access scoring."""

    id: str
    lat: float
    lon: float
    label: str = ""


class NeighbourhoodAccessConfig(BaseModel, frozen=True):
    """Travel-time / road-distance access scores to city hubs (BIN-90).

    When ``base_url`` is empty, the refresh job uses haversine + ``avg_speed_kmh``.
    Point ``base_url`` at a self-hosted OSRM instance for real routing.
    """

    enabled: bool = True
    interval_minutes: int = 1440
    base_url: str = ""
    mode: str = "driving"
    max_minutes: float = 45.0
    avg_speed_kmh: float = 30.0
    request_timeout_sec: float = 20.0
    hubs: dict[str, list[AccessHubConfig]] = Field(default_factory=dict)


class NeighbourhoodTransitConfig(BaseModel, frozen=True):
    """Transit proximity radii and mode weights (BIN-89).

    Used by ``core.transit_proximity`` when scoring neighbourhoods from
    GTFS / OSM stop files. Metro/BRT weigh higher than bus.
    """

    count_radius_m: float = 400.0
    max_radius_m: float = 1200.0
    nearest_weight: float = 0.7
    density_weight: float = 0.3
    density_cap: float = 8.0
    mode_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "metro": 1.0,
            "brt": 0.9,
            "rail": 0.85,
            "bus": 0.55,
            "other": 0.4,
        }
    )


class ListingClaimStatsConfig(BaseModel, frozen=True):
    """Aggregate listing LLM green/red flags by neighbourhood (BIN-93).

    Weak secondary signal only — never overwrites amenity/safety scores.
    Default ``enabled=false`` so beat does not run until an operator opts in.
    """

    enabled: bool = False
    top_n: int = 10
    interval_hours: float = 24.0
    min_sample_size: int = 1


class NeighbourhoodQualityConfig(BaseModel, frozen=True):
    """Objective neighbourhood quality fill-job settings (BIN-86+)."""

    osm_amenities: OsmAmenitiesConfig = Field(default_factory=OsmAmenitiesConfig)
    transit: NeighbourhoodTransitConfig = Field(
        default_factory=NeighbourhoodTransitConfig
    )
    listing_claim_stats: ListingClaimStatsConfig = Field(
        default_factory=ListingClaimStatsConfig
    )


class AppConfig(BaseModel, frozen=True):
    """Top-level frozen configuration object.

    This is the single object the rest of the application should consume::

        from src.infra.config import get_config
        cfg = get_config()
        engine = create_async_engine(cfg.database.url)
    """

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)
    gpu: GPUConfig = Field(default_factory=GPUConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    pipeline_metrics: PipelineMetricsConfig = Field(default_factory=PipelineMetricsConfig)
    neighbourhood_quality: NeighbourhoodQualityConfig = Field(
        default_factory=NeighbourhoodQualityConfig
    )
    neighbourhood_access: NeighbourhoodAccessConfig = Field(
        default_factory=NeighbourhoodAccessConfig
    )
    image_storage_path: str = "data/images"

# ---------------------------------------------------------------------------
# YAML loading helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file.  Raises ``ConfigError`` on I/O or parse
    errors."""
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Configuration file {path} must contain a mapping at the top level, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


def _parse_database_url(url: str) -> dict[str, Any]:
    """Parse a PostgreSQL connection URL into individual config fields."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "name": (parsed.path.lstrip("/")) or "imoveis",
        "user": parsed.username or "imoveis",
        "password": parsed.password or "",
    }


def _set_nested(d: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using dot notation (e.g. ``ai.visual_model``)."""
    keys = dotted_key.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    # Attempt to coerce to the original type if the key already exists
    target = keys[-1]
    existing = d.get(target)
    if existing is not None:
        try:
            if isinstance(existing, bool):
                value = str(value).lower() in ("true", "1", "yes")
            elif isinstance(existing, int):
                value = int(value)  # type: ignore[assignment]
            elif isinstance(existing, float):
                value = float(value)  # type: ignore[assignment]
        except (ValueError, TypeError):
            pass  # keep the string value
    d[target] = value


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Merge environment-variable overrides into the raw config dict.

    Supported patterns (checked in order):

    1. ``DATABASE_URL`` — parsed into ``database.*`` fields
    2. ``REDIS_URL``    — parsed into ``redis.*`` fields
    3. ``AI_MODEL`` / ``AI_TEXT_MODEL`` / ``AI_EMBEDDING_MODEL`` / ``OLLAMA_HOST``
    4. ``API_KEY`` / ``JWT_SECRET`` / ``ADMIN_USER`` / ``ADMIN_PASS`` → ``auth.*``
    5. ``IMOVEIS_<SECTION>__<KEY>`` — generic override for any leaf value
    """
    # 1. DATABASE_URL → database section
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        data.setdefault("database", {})
        data["database"].update(_parse_database_url(db_url))

    # 2. REDIS_URL → redis section
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        parsed = urlparse(redis_url)
        data.setdefault("redis", {})
        data["redis"]["host"] = parsed.hostname or "localhost"
        data["redis"]["port"] = parsed.port or 6379
        data["redis"]["db"] = int((parsed.path or "/0").lstrip("/") or "0")
        data["redis"]["password"] = parsed.password or ""

    # 3. AI_MODEL → ai.visual_model
    ai_model = os.environ.get("AI_MODEL")
    if ai_model:
        data.setdefault("ai", {})
        data["ai"]["visual_model"] = ai_model

    # 3.1 AI_TEXT_MODEL → ai.text_model
    ai_text_model = os.environ.get("AI_TEXT_MODEL")
    if ai_text_model:
        data.setdefault("ai", {})
        data["ai"]["text_model"] = ai_text_model

    # 3.2 AI_EMBEDDING_MODEL → ai.embedding_model
    ai_embedding_model = os.environ.get("AI_EMBEDDING_MODEL")
    if ai_embedding_model:
        data.setdefault("ai", {})
        data["ai"]["embedding_model"] = ai_embedding_model

    # 3.3 AI_NUM_CTX → ai.num_ctx
    ai_num_ctx = os.environ.get("AI_NUM_CTX")
    if ai_num_ctx:
        data.setdefault("ai", {})
        data["ai"]["num_ctx"] = int(ai_num_ctx)

    # 3.5. OLLAMA_HOST → ai.ollama_url
    ollama_host = os.environ.get("OLLAMA_HOST")
    if ollama_host:
        data.setdefault("ai", {})
        data["ai"]["ollama_url"] = ollama_host

    # 3.6 Auth credentials → auth.* (prefer dedicated env names for DX / CI)
    data.setdefault("auth", {})
    api_key = os.environ.get("API_KEY")
    if api_key is not None:
        data["auth"]["api_key"] = api_key
    jwt_secret = os.environ.get("JWT_SECRET")
    if jwt_secret is not None:
        data["auth"]["jwt_secret"] = jwt_secret
    admin_user = os.environ.get("ADMIN_USER")
    if admin_user is not None:
        data["auth"]["admin_user"] = admin_user
    admin_pass = os.environ.get("ADMIN_PASS")
    if admin_pass is not None:
        data["auth"]["admin_pass"] = admin_pass

    # 4. Generic IMOVEIS_* overrides
    prefix = _ENV_PREFIX
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        dotted = key[len(prefix) :].lower().replace("__", ".")
        _set_nested(data, dotted, value)

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from a YAML file, apply env overrides, and validate.

    Parameters
    ----------
    path:
        Path to the YAML config file.  Defaults to ``configs/app_config.yaml``
        relative to the repository root.

    Raises
    ------
    ConfigError
        If the file is missing, unparseable, or the resulting data fails
        Pydantic validation.
    """
    config_path = path or _DEFAULT_CONFIG_PATH
    raw = _load_yaml(config_path)
    raw = _apply_env_overrides(raw)
    try:
        return AppConfig.model_validate(raw)
    except Exception as exc:
        raise ConfigError(f"Configuration validation failed: {exc}") from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return the cached singleton ``AppConfig``.

    The config is loaded from the default path on the first call and cached
    for all subsequent calls.  Use ``load_config()`` directly when you need
    to load from a non-default path (e.g. in tests).
    """
    return load_config()
