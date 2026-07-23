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
from typing import Any
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
        return f"postgresql://{self.user}:{self.password}" f"@{self.host}:{self.port}/{self.name}"


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
    semaphore_limit: int = 1


class AIConfig(BaseModel, frozen=True):
    """AI / VLM settings.

    Read from the ``ai:`` section of ``app_config.yaml``.  Individual model
    names can be overridden via ``AI_MODEL`` (visual) and ``AI_TEXT_MODEL``
    (text) environment variables.
    """

    backend: str = "ollama"  # ollama | lmstudio
    ollama_url: str = "http://localhost:11434"
    lmstudio_url: str = "http://localhost:1234"
    visual_model: str = "llava"
    text_model: str = "llama3"
    embedding_model: str = "nomic-embed-text"
    timeout: int = 120
    max_tokens: int = 1024
    visual_weight: float = 0.6
    text_weight: float = 0.4
    max_images_per_property: int = 5
    max_description_chars: int = 1000
    output_language: str = "pt-br"


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


class ScrapingConfig(BaseModel, frozen=True):
    """Web scraping defaults and per-platform overrides."""

    default_delay: float = 2.0
    user_agent: str = "imoveis-bot/0.1 (real-estate-research)"
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)


class FeaturesConfig(BaseModel, frozen=True):
    """Feature flags for optional functionality."""

    property_enrichment: bool = False
    price_alerts: bool = False


class ScoringConfig(BaseModel, frozen=True):
    """Scoring defaults and weights."""

    stat_weight: float = 0.5
    ai_weight: float = 0.5
    recalculate_on_enrichment: bool = True


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
        raise ConfigError(f"Configuration file {path} must contain a mapping at the top level, " f"got {type(data).__name__}")
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
    3. ``AI_MODEL``     — overrides ``ai.visual_model``
    4. ``OLLAMA_HOST``  — overrides ``ai.ollama_url``
    5. ``IMOVEIS_<SECTION>_<KEY>`` — generic override for any leaf value
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

    # 3.5. OLLAMA_HOST → ai.ollama_url
    ollama_host = os.environ.get("OLLAMA_HOST")
    if ollama_host:
        data.setdefault("ai", {})
        data["ai"]["ollama_url"] = ollama_host

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
