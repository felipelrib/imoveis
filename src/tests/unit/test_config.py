"""Unit tests for the YAML config loader with Pydantic validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.core.exceptions import ConfigError
from src.infra.config import AppConfig, get_config, load_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_YAML = """\
database:
  host: localhost
  port: 5432
  name: testdb
  user: testuser
  password: testpass
  pool_size: 5
  max_overflow: 2
redis:
  host: localhost
  port: 6379
  db: 0
  password: ""
celery:
  task_serializer: json
  result_serializer: json
  accept_content:
    - json
  timezone: America/Sao_Paulo
  beat_schedule: {}
gpu:
  enabled: true
  semaphore_limit: 1
ai:
  providers:
    ollama:
      base_url: http://localhost:11434
      default_model: llava
      request_timeout: 120
      max_retries: 3
scraping:
  default_delay: 2.0
  user_agent: "test-agent/1.0"
  platforms: {}
features:
  property_enrichment: false
  price_alerts: false
"""


_CONFIG_ENV_KEYS = [
    "DATABASE_URL",
    "REDIS_URL",
    "AI_MODEL",
    "OLLAMA_HOST",
]


@pytest.fixture(autouse=True)
def _clear_config_env(monkeypatch):
    """Remove env-var overrides that conflict with deterministic config tests.

    Docker containers (e.g. CI / docker-compose) set DATABASE_URL and
    REDIS_URL, which would override the test YAML values.  We temporarily
    clear them for every test in this module, and also remove any
    ``IMOVEIS_*`` generic overrides.

    We also clear ``get_config()``'s lru_cache so the singleton picks up
    the clean environment.
    """
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in list(os.environ):
        if key.startswith("IMOVEIS_"):
            monkeypatch.delenv(key, raising=False)
    get_config.cache_clear()


def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write YAML content to a temp file and return the path."""
    cfg_file = tmp_path / "app_config.yaml"
    cfg_file.write_text(content)
    return cfg_file


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_config_from_yaml(tmp_path: Path):
    """Valid YAML is loaded and parsed into an AppConfig."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    assert isinstance(cfg, AppConfig)
    assert cfg.database.host == "localhost"
    assert cfg.database.port == 5432
    assert cfg.database.name == "testdb"
    assert cfg.database.user == "testuser"
    assert cfg.database.password == "testpass"
    assert cfg.redis.host == "localhost"
    assert cfg.redis.port == 6379
    assert cfg.ai.providers.ollama.default_model == "llava"
    assert cfg.gpu.enabled is True
    assert cfg.features.property_enrichment is False


@pytest.mark.unit
def test_database_url_property(tmp_path: Path):
    """DatabaseConfig.url computes a connection string from fields."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    expected = "postgresql://testuser:testpass@localhost:5432/testdb"
    assert cfg.database.url == expected


@pytest.mark.unit
def test_redis_url_property(tmp_path: Path):
    """RedisConfig.url computes a connection string from fields."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    assert cfg.redis.url == "redis://localhost:6379/0"


@pytest.mark.unit
def test_redis_url_with_password(tmp_path: Path):
    """RedisConfig.url includes password when set."""
    yaml_content = MINIMAL_YAML.replace('password: ""', 'password: "secret123"')
    cfg_file = _write_yaml(tmp_path, yaml_content)
    cfg = load_config(cfg_file)

    assert cfg.redis.url == "redis://:secret123@localhost:6379/0"


# ---------------------------------------------------------------------------
# Tests: missing file
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_config_file_raises_config_error():
    """Loading from a non-existent path raises ConfigError."""
    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config(Path("/nonexistent/path/app_config.yaml"))


# ---------------------------------------------------------------------------
# Tests: invalid YAML
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_invalid_yaml_raises_config_error(tmp_path: Path):
    """Malformed YAML content raises ConfigError."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("{{{{invalid yaml:::\n  - broken")

    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(bad_file)


@pytest.mark.unit
def test_non_dict_yaml_raises_config_error(tmp_path: Path):
    """YAML that is not a mapping raises ConfigError."""
    list_file = tmp_path / "list.yaml"
    list_file.write_text("- item1\n- item2\n")

    with pytest.raises(ConfigError, match="must contain a mapping"):
        load_config(list_file)


# ---------------------------------------------------------------------------
# Tests: missing required fields (Pydantic validation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_yaml_loads_with_defaults(tmp_path: Path):
    """An empty YAML file loads successfully with all defaults."""
    cfg_file = _write_yaml(tmp_path, "# empty config\n")
    cfg = load_config(cfg_file)

    assert isinstance(cfg, AppConfig)
    assert cfg.database.host == "localhost"
    assert cfg.database.port == 5432
    assert cfg.gpu.semaphore_limit == 1


# ---------------------------------------------------------------------------
# Tests: environment variable overrides
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_database_url_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """DATABASE_URL env var overrides database fields."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("DATABASE_URL", "postgresql://envuser:envpass@dbhost:5433/envdb")

    cfg = load_config(cfg_file)

    assert cfg.database.host == "dbhost"
    assert cfg.database.port == 5433
    assert cfg.database.name == "envdb"
    assert cfg.database.user == "envuser"
    assert cfg.database.password == "envpass"


@pytest.mark.unit
def test_redis_url_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """REDIS_URL env var overrides redis fields."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("REDIS_URL", "redis://:mypassword@redis-host:6380/2")

    cfg = load_config(cfg_file)

    assert cfg.redis.host == "redis-host"
    assert cfg.redis.port == 6380
    assert cfg.redis.db == 2
    assert cfg.redis.password == "mypassword"


@pytest.mark.unit
def test_ai_model_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """AI_MODEL env var overrides the default Ollama model."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("AI_MODEL", "deepseek-r1:14b")

    cfg = load_config(cfg_file)

    assert cfg.ai.providers.ollama.default_model == "deepseek-r1:14b"


@pytest.mark.unit
def test_generic_imoveis_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_<SECTION>_<KEY> env var overrides a nested config value."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_APP__DEBUG", "true")

    cfg = load_config(cfg_file)

    assert cfg.app.debug is True


@pytest.mark.unit
def test_imoveis_env_override_int_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_ env vars are coerced to the target field's type."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_APP__API_PORT", "9999")

    cfg = load_config(cfg_file)

    assert cfg.app.api_port == 9999


# ---------------------------------------------------------------------------
# Tests: singleton / caching
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_config_returns_same_instance():
    """get_config() returns the same cached object on repeated calls."""
    a = get_config()
    b = get_config()
    assert a is b


@pytest.mark.unit
def test_get_config_returns_app_config():
    """get_config() returns an AppConfig instance."""
    cfg = get_config()
    assert isinstance(cfg, AppConfig)


# ---------------------------------------------------------------------------
# Tests: frozen model
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_is_frozen(tmp_path: Path):
    """Attempting to mutate a field on AppConfig raises an error."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    with pytest.raises(Exception):  # Pydantic raises ValidationError or AttributeError
        cfg.app.debug = True  # type: ignore[misc]


@pytest.mark.unit
def test_database_config_is_frozen(tmp_path: Path):
    """Attempting to mutate a nested config field raises an error."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    with pytest.raises(Exception):
        cfg.database.host = "changed"  # type: ignore[misc]
