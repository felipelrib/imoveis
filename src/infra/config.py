"""Centralized configuration loader.

Single source of truth for all settings. Reads from configs/app_config.yaml
and allows environment variable overrides for secrets.

Usage:
    from infra.config import get_config
    cfg = get_config()
    cfg.database_url  # str
    cfg.redis_url     # str
    cfg.ai.model      # str
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass(frozen=True)
class PlatformConfig:
    """Per-platform scraper settings."""
    base_url: str = ""
    enabled: bool = True
    rate_limit: int = 30
    jitter_min: float = 2.0
    jitter_max: float = 7.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DedupeConfig:
    """Deduplication thresholds."""
    radius_m: float = 50.0
    area_tolerance_m2: float = 2.0
    text_similarity_threshold: float = 0.65
    text_similarity_algorithm: str = "jaro_winkler"  # jaro_winkler | token_sort


@dataclass(frozen=True)
class ScoringConfig:
    """Scoring engine weights and settings."""
    stat_weight: float = 0.5
    ai_weight: float = 0.5


@dataclass(frozen=True)
class AIConfig:
    """Local VLM / Ollama settings."""
    backend: str = "ollama"  # ollama | lmstudio
    ollama_url: str = "http://localhost:11434"
    lmstudio_url: str = "http://localhost:1234"
    model: str = "llama3.2-vision"
    timeout_seconds: int = 120
    max_tokens: int = 1024


@dataclass(frozen=True)
class GPUConfig:
    """GPU resource management."""
    semaphore_limit: int = 1
    semaphore_name: str = "gpu"


@dataclass(frozen=True)
class ProxyConfig:
    """Proxy settings (placeholder for future rotating residential proxies)."""
    enabled: bool = False
    url: Optional[str] = None
    rotation_strategy: str = "round_robin"  # round_robin | random
    pool: list = field(default_factory=list)


@dataclass(frozen=True)
class AppConfig:
    """Root application config — single source of truth."""
    database_url: str = "postgresql://user:password@localhost:5432/realestate"
    redis_url: str = "redis://localhost:6379/0"
    platforms: Dict[str, PlatformConfig] = field(default_factory=dict)
    dedup: DedupeConfig = field(default_factory=DedupeConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    gpu: GPUConfig = field(default_factory=GPUConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    image_storage_path: str = "data/images"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_PATHS = [
    Path("configs/app_config.yaml"),
    Path("../configs/app_config.yaml"),        # when CWD is src/
    Path(__file__).resolve().parents[2] / "configs" / "app_config.yaml",
]

_cached_config: Optional[AppConfig] = None


def _find_config_file() -> Optional[Path]:
    for p in _CONFIG_PATHS:
        if p.exists():
            return p
    return None


def _parse_platform(name: str, raw: Dict[str, Any]) -> PlatformConfig:
    return PlatformConfig(
        base_url=raw.get("base_url", ""),
        enabled=raw.get("enabled", True),
        rate_limit=raw.get("rate_limit", 30),
        jitter_min=float(raw.get("jitter_min", 2)),
        jitter_max=float(raw.get("jitter_max", 7)),
        extra={k: v for k, v in raw.items()
               if k not in ("base_url", "enabled", "rate_limit", "jitter_min", "jitter_max")},
    )


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from YAML, with env-var overrides for secrets."""
    raw: Dict[str, Any] = {}
    config_path = path or _find_config_file()
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # Env overrides (secrets should NOT live in YAML)
    database_url = os.getenv(
        "DATABASE_URL",
        raw.get("database", {}).get("url", AppConfig.database_url),
    )
    redis_url = os.getenv("REDIS_URL", raw.get("redis_url", AppConfig.redis_url))

    # Platforms
    platforms = {}
    for name, pcfg in raw.get("platforms", {}).items():
        platforms[name] = _parse_platform(name, pcfg or {})

    # Sub-configs
    dedup_raw = raw.get("dedup", {}) or {}
    scoring_raw = raw.get("scoring", {}) or {}
    ai_raw = raw.get("ai", {}) or {}
    gpu_raw = raw.get("gpu", {}) or {}
    proxy_raw = raw.get("proxy", {}) or {}

    return AppConfig(
        database_url=database_url,
        redis_url=redis_url,
        platforms=platforms,
        dedup=DedupeConfig(
            radius_m=float(dedup_raw.get("radius_m", 50.0)),
            area_tolerance_m2=float(dedup_raw.get("area_tolerance_m2", 2.0)),
            text_similarity_threshold=float(dedup_raw.get("text_similarity_threshold", 0.65)),
            text_similarity_algorithm=dedup_raw.get("text_similarity_algorithm", "jaro_winkler"),
        ),
        scoring=ScoringConfig(
            stat_weight=float(scoring_raw.get("stat_weight", 0.5)),
            ai_weight=float(scoring_raw.get("ai_weight", 0.5)),
        ),
        ai=AIConfig(
            backend=ai_raw.get("backend", "ollama"),
            ollama_url=os.getenv("OLLAMA_HOST", ai_raw.get("ollama_url", "http://localhost:11434")),
            lmstudio_url=ai_raw.get("lmstudio_url", "http://localhost:1234"),
            model=os.getenv("AI_MODEL", ai_raw.get("default_model", "llama3.2-vision")),
            timeout_seconds=int(ai_raw.get("timeout_seconds", 120)),
            max_tokens=int(ai_raw.get("max_tokens", 1024)),
        ),
        gpu=GPUConfig(
            semaphore_limit=int(gpu_raw.get("semaphore_limit", 1)),
            semaphore_name=gpu_raw.get("semaphore_name", "gpu"),
        ),
        proxy=ProxyConfig(
            enabled=proxy_raw.get("enabled", False),
            url=proxy_raw.get("url"),
            rotation_strategy=proxy_raw.get("rotation_strategy", "round_robin"),
            pool=proxy_raw.get("pool", []),
        ),
        image_storage_path=raw.get("image_storage_path", "data/images"),
    )


def get_config() -> AppConfig:
    """Return cached singleton config. Call reload_config() to refresh."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def reload_config() -> AppConfig:
    """Force-reload config from disk."""
    global _cached_config
    _cached_config = load_config()
    return _cached_config
