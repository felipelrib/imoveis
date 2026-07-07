from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import os
from pathlib import Path

@dataclass(frozen=True)
class PlatformConfig:
    name: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    delay_range: tuple = (1, 3)  # seconds between requests
    max_retries: int = 3
    timeout: int = 30
    enabled: bool = True
    rate_limit: Optional[int] = None

@dataclass(frozen=True)
class DedupeConfig:
    enabled: bool = True
    similarity_threshold: float = 0.85

@dataclass(frozen=True)
class ScoringConfig:
    ai_weight: float = 0.5
    stat_weight: float = 0.5

@dataclass(frozen=True)
class AIConfig:
    ollama_url: str = "http://localhost:11434"
    model_name: str = "llama3"
    timeout: int = 30

@dataclass(frozen=True)
class GPUConfig:
    max_concurrent_jobs: int = 1
    redis_url: str = "redis://localhost:6379/0"

@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool = False
    url: Optional[str] = None

@dataclass(frozen=True)
class AppConfig:
    database_url: str = "postgresql://user:password@localhost:5432/property_db"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    redis_url: str = "redis://localhost:6379/0"
    platforms: Dict[str, PlatformConfig] = field(default_factory=dict)
    dedupe: DedupeConfig = field(default_factory=DedupeConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    image_storage_path: str = "data/images"
    gpu: GPUConfig = field(default_factory=GPUConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)

def _find_config_file() -> Optional[Path]:
    """Find configuration file in standard locations."""
    config_paths = [
        Path("config.yaml"),
        Path("./config.yaml"),
        Path("../config.yaml"),
        Path("/etc/property-scraper/config.yaml"),
    ]
    
    for path in config_paths:
        if path.exists():
            return path
    return None

def _parse_platform(name: str, raw: Dict[str, Any]) -> PlatformConfig:
    """Parse platform configuration."""
    return PlatformConfig(
        name=name,
        url=raw.get("url", ""),
        headers=raw.get("headers", {}),
        delay_range=tuple(raw.get("delay_range", (1, 3))),
        max_retries=raw.get("max_retries", 3),
        timeout=raw.get("timeout", 30),
    )

def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load configuration from file or environment."""
    # This is a simplified implementation
    # In reality, this would parse YAML/JSON config files
    
    # For now, return default values
    platforms = {
        "quintoandar": PlatformConfig(
            name="quintoandar",
            url="https://www.quintoandar.com.br",
            delay_range=(1, 3),
            max_retries=3,
        )
    }
    
    return AppConfig(
        database_url=os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/property_db"),
        celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        platforms=platforms,
        dedupe=DedupeConfig(),
        scoring=ScoringConfig(),
        ai=AIConfig(ollama_url=os.getenv("OLLAMA_HOST", "http://localhost:11434")),
        gpu=GPUConfig(),
        proxy=ProxyConfig(),
    )

def get_config() -> AppConfig:
    """Get the global configuration."""
    return load_config()
