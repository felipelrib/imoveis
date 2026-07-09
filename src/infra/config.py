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
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, model_validator

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


class OllamaProviderConfig(BaseModel, frozen=True):
    """Settings for the Ollama AI backend."""

    base_url: str = "http://localhost:11434"
    default_model: str = "devstral:24b"
    request_timeout: int = 120
    max_retries: int = 3


class AIProvidersConfig(BaseModel, frozen=True):
    """Map of AI provider configs (currently only ``ollama``)."""

    ollama: OllamaProviderConfig = Field(default_factory=OllamaProviderConfig)


class AIConfig(BaseModel, frozen=True):
    """AI / VLM settings."""

    providers: AIProvidersConfig = Field(default_factory=AIProvidersConfig)


class PlatformConfig(BaseModel, frozen=True):
    """Settings for a single real-estate scraping platform."""

    enabled: bool = True
    base_url: str = ""
    listing_selector: str = ""
    pagination_strategy: str = ""
    scrape_interval: int = 60  # minutes between scheduled scrapes (0 = manual only)


class ScrapingConfig(BaseModel, frozen=True):
    """Web scraping defaults and per-platform overrides."""

    default_delay: float = 2.0
    user_agent: str = "imoveis-bot/0.1 (real-estate-research)"
    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)


class FeaturesConfig(BaseModel, frozen=True):
    """Feature flags for optional functionality."""

    property_enrichment: bool = False
    price_alerts: bool = False


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
    """Set a value in a nested dict using dot notation (e.g. ``ai.providers.ollama.default_model``)."""
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
    3. ``AI_MODEL``     — overrides ``ai.providers.ollama.default_model``
    4. ``OLLAMA_HOST``  — overrides ``ai.providers.ollama.base_url``
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

    # 3. AI_MODEL → ai.providers.ollama.default_model
    ai_model = os.environ.get("AI_MODEL")
    if ai_model:
        data.setdefault("ai", {})
        data["ai"].setdefault("providers", {})
        data["ai"]["providers"].setdefault("ollama", {})
        data["ai"]["providers"]["ollama"]["default_model"] = ai_model

    # 3.5. OLLAMA_HOST → ai.providers.ollama.base_url
    ollama_host = os.environ.get("OLLAMA_HOST")
    if ollama_host:
        data.setdefault("ai", {})
        data["ai"].setdefault("providers", {})
        data["ai"]["providers"].setdefault("ollama", {})
        data["ai"]["providers"]["ollama"]["base_url"] = ollama_host

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
