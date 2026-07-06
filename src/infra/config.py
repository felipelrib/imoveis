import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from pathlib import Path
import yaml
import os

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PlatformConfig:
    """Configuration for a scraping platform."""
    
    name: str
    enabled: bool = True
    base_url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    rate_limit: int = 1  # requests per second
    delay_range: tuple = field(default_factory=lambda: (0.5, 2.0))
    retries: int = 3

@dataclass(frozen=True)
class DedupeConfig:
    """Configuration for deduplication."""
    
    threshold: float = 0.8
    algorithm: str = "jaro_winkler"
    enabled: bool = True

@dataclass(frozen=True)
class ScoringConfig:
    """Configuration for scoring."""
    
    ai_weight: float = 0.5
    statistical_weight: float = 0.5
    enabled: bool = True

@dataclass(frozen=True)
class AIConfig:
    """Configuration for AI services."""
    
    ollama_url: str = "http://localhost:11434"
    lm_studio_url: str = "http://localhost:1234"
    timeout: int = 30
    enabled: bool = True

@dataclass(frozen=True)
class GPUConfig:
    """Configuration for GPU usage."""
    
    max_concurrent: int = 1
    enabled: bool = True

@dataclass(frozen=True)
class ProxyConfig:
    """Configuration for proxy usage."""
    
    enabled: bool = False
    url: str = ""
    username: str = ""
    password: str = ""

@dataclass(frozen=True)
class AppConfig:
    """Main application configuration."""
    
    platforms: Dict[str, PlatformConfig] = field(default_factory=dict)
    dedupe: DedupeConfig = field(default_factory=DedupeConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    gpu: GPUConfig = field(default_factory=GPUConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    debug: bool = False

def _find_config_file() -> Optional[Path]:
    """Find configuration file in standard locations."""
    config_paths = [
        Path("config.yaml"),
        Path("config.yml"),
        Path("/etc/real-estate-scraper/config.yaml"),
        Path(os.path.expanduser("~/.real-estate-scraper/config.yaml")),
    ]
    
    for path in config_paths:
        if path.exists():
            return path
    return None

def _parse_platform(name: str, raw: Dict[str, Any]) -> PlatformConfig:
    """Parse platform configuration."""
    try:
        return PlatformConfig(
            name=name,
            enabled=raw.get("enabled", True),
            base_url=raw.get("base_url", ""),
            headers=raw.get("headers", {}),
            rate_limit=raw.get("rate_limit", 1),
            delay_range=tuple(raw.get("delay_range", [0.5, 2.0])),
            retries=raw.get("retries", 3)
        )
    except Exception as e:
        logger.error(f"Error parsing platform config for {name}: {e}")
        # Retornar configuração padrão em caso de erro
        return PlatformConfig(name=name)

def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load configuration from file."""
    try:
        if path is None:
            path = _find_config_file()
            
        if path is None:
            logger.warning("No config file found, using defaults")
            return AppConfig()
            
        with open(path, 'r') as f:
            raw_config = yaml.safe_load(f)
            
        platforms = {}
        if "platforms" in raw_config:
            for name, platform_config in raw_config["platforms"].items():
                platforms[name] = _parse_platform(name, platform_config)
                
        return AppConfig(
            platforms=platforms,
            dedupe=DedupeConfig(
                threshold=raw_config.get("dedupe", {}).get("threshold", 0.8),
                algorithm=raw_config.get("dedupe", {}).get("algorithm", "jaro_winkler"),
                enabled=raw_config.get("dedupe", {}).get("enabled", True)
            ),
            scoring=ScoringConfig(
                ai_weight=raw_config.get("scoring", {}).get("ai_weight", 0.5),
                statistical_weight=raw_config.get("scoring", {}).get("statistical_weight", 0.5),
                enabled=raw_config.get("scoring", {}).get("enabled", True)
            ),
            ai=AIConfig(
                ollama_url=raw_config.get("ai", {}).get("ollama_url", "http://localhost:11434"),
                lm_studio_url=raw_config.get("ai", {}).get("lm_studio_url", "http://localhost:1234"),
                timeout=raw_config.get("ai", {}).get("timeout", 30),
                enabled=raw_config.get("ai", {}).get("enabled", True)
            ),
            gpu=GPUConfig(
                max_concurrent=raw_config.get("gpu", {}).get("max_concurrent", 1),
                enabled=raw_config.get("gpu", {}).get("enabled", True)
            ),
            proxy=ProxyConfig(
                enabled=raw_config.get("proxy", {}).get("enabled", False),
                url=raw_config.get("proxy", {}).get("url", ""),
                username=raw_config.get("proxy", {}).get("username", ""),
                password=raw_config.get("proxy", {}).get("password", "")
            ),
            debug=raw_config.get("debug", False)
        )
        
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return AppConfig()

def get_config() -> AppConfig:
    """Get the global configuration."""
    # Em uma implementação real, isso poderia ser armazenado em cache
    return load_config()
