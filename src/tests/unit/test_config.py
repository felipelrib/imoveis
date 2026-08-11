"""Unit tests for the YAML config loader with Pydantic validation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.enrichment import EnrichmentBackend, EnrichmentTaskClass
from src.core.exceptions import ConfigError
from src.infra.config import AppConfig, get_config, load_config


def _yaml_with_ai(ai_extra: str) -> str:
    """Return MINIMAL_YAML with extra keys inserted under its ``ai:`` mapping.

    ``ai_extra`` must be 2-space-indented YAML (siblings of ``providers:``).
    """
    return MINIMAL_YAML.replace("ai:\n", "ai:\n" + ai_extra, 1)

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
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "API_KEY",
    "JWT_SECRET",
    "ADMIN_USER",
    "ADMIN_PASS",
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
    assert cfg.ai.visual_model == "qwen2.5vl:7b"
    assert cfg.ai.text_model == "qwen2.5vl:7b"
    assert cfg.ai.embedding_model == "bge-m3"
    assert cfg.ai.num_ctx == 16384
    assert cfg.gpu.enabled is True
    assert cfg.features.property_enrichment is False
    assert cfg.scraping.photo_gate.enabled is True
    assert cfg.scraping.photo_gate.floor_min == 8
    assert cfg.scraping.photo_gate.coverage_ratio == 1.0
    assert cfg.scraping.photo_gate.min_photos is None
    assert cfg.scraping.availability_recheck.enabled is True
    assert cfg.scraping.availability_recheck.interval_minutes == 360
    assert cfg.scraping.availability_recheck.batch_size == 50
    assert cfg.scraping.availability_recheck.stale_after_hours == 24
    # Cloudflare bypass (BIN-246/BIN-247): model defaults when the section is
    # absent from the (minimal) fixture — off, OLX target, auto-fallback on.
    assert cfg.scraping.cloudflare_bypass.enabled is False
    assert cfg.scraping.cloudflare_bypass.platforms == ["olx"]
    assert cfg.scraping.cloudflare_bypass.auto_fallback is True
    assert cfg.scraping.cloudflare_bypass.endpoint.endswith("/v1")


@pytest.mark.unit
def test_cloudflare_bypass_auto_fallback_defaults_on():
    """A new Cloudflare-gated provider must be covered without config edits:
    the model default for auto_fallback is on (BIN-247)."""
    from infra.config import CloudflareBypassConfig

    assert CloudflareBypassConfig().auto_fallback is True


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
    missing = Path("/nonexistent/path/app_config.yaml")
    with pytest.raises(ConfigError, match="Configuration file not found"):
        load_config(missing)


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
    assert cfg.gpu.semaphore_limit == 2


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

    assert cfg.ai.visual_model == "deepseek-r1:14b"


@pytest.mark.unit
def test_gemini_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """GEMINI_API_KEY / GEMINI_MODEL env vars land on ai.* (key never in YAML)."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("GEMINI_API_KEY", "env-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemma-4-31b-it")

    cfg = load_config(cfg_file)

    assert cfg.ai.gemini_api_key == "env-gemini-key"
    assert cfg.ai.gemini_model == "gemma-4-31b-it"


@pytest.mark.unit
def test_generic_imoveis_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_<SECTION>_<KEY> env var overrides a nested config value."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_APP__DEBUG", "true")

    cfg = load_config(cfg_file)

    assert cfg.app.debug is True


@pytest.mark.unit
def test_api_key_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """API_KEY env var maps into auth.api_key."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("API_KEY", "from-api-key-env")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    cfg = load_config(cfg_file)

    assert cfg.auth.api_key == "from-api-key-env"
    assert cfg.auth.principal_id == "default"


@pytest.mark.unit
def test_imoveis_auth_principal_id_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_AUTH__PRINCIPAL_ID overrides auth.principal_id."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_AUTH__PRINCIPAL_ID", "operator-1")

    cfg = load_config(cfg_file)

    assert cfg.auth.principal_id == "operator-1"


@pytest.mark.unit
def test_jwt_secret_and_admin_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """JWT_SECRET / ADMIN_USER / ADMIN_PASS map into auth.*."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("JWT_SECRET", "unit-jwt-secret")
    monkeypatch.setenv("ADMIN_USER", "ops")
    monkeypatch.setenv("ADMIN_PASS", "ops-pass")

    cfg = load_config(cfg_file)

    assert cfg.auth.jwt_secret == "unit-jwt-secret"
    assert cfg.auth.admin_user == "ops"
    assert cfg.auth.admin_pass == "ops-pass"


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

    with pytest.raises((ValidationError, AttributeError)):
        cfg.app.debug = True  # type: ignore[misc]


@pytest.mark.unit
def test_database_config_is_frozen(tmp_path: Path):
    """Attempting to mutate a nested config field raises an error."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    with pytest.raises((ValidationError, AttributeError)):
        cfg.database.host = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: proxy settings (BIN-47 / Story 3.1)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_proxy_disabled_by_default(tmp_path: Path):
    """Absent or disabled proxy block exposes defaults with empty pool."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)

    assert cfg.proxy.enabled is False
    assert cfg.proxy.url is None
    assert cfg.proxy.rotation_strategy == "round_robin"
    assert cfg.proxy.pool == []


@pytest.mark.unit
def test_proxy_disabled_explicit(tmp_path: Path):
    """Explicit proxy.enabled: false keeps url/pool unset."""
    yaml_content = MINIMAL_YAML + """\
proxy:
  enabled: false
  url: null
  rotation_strategy: round_robin
  pool: []
"""
    cfg_file = _write_yaml(tmp_path, yaml_content)
    cfg = load_config(cfg_file)

    assert cfg.proxy.enabled is False
    assert cfg.proxy.url is None
    assert cfg.proxy.pool == []


@pytest.mark.unit
def test_proxy_single_url_mode(tmp_path: Path):
    """Single-url mode: enabled with one url and empty pool."""
    yaml_content = MINIMAL_YAML + """\
proxy:
  enabled: true
  url: http://proxy.example:8080
  rotation_strategy: round_robin
  pool: []
"""
    cfg_file = _write_yaml(tmp_path, yaml_content)
    cfg = load_config(cfg_file)

    assert cfg.proxy.enabled is True
    assert cfg.proxy.url == "http://proxy.example:8080"
    assert cfg.proxy.rotation_strategy == "round_robin"
    assert cfg.proxy.pool == []


@pytest.mark.unit
def test_proxy_pool_mode(tmp_path: Path):
    """Pool mode: enabled with multiple URLs and random strategy."""
    yaml_content = MINIMAL_YAML + """\
proxy:
  enabled: true
  url: null
  rotation_strategy: random
  pool:
    - http://proxy1.example:8080
    - http://proxy2.example:8080
"""
    cfg_file = _write_yaml(tmp_path, yaml_content)
    cfg = load_config(cfg_file)

    assert cfg.proxy.enabled is True
    assert cfg.proxy.url is None
    assert cfg.proxy.rotation_strategy == "random"
    assert cfg.proxy.pool == [
        "http://proxy1.example:8080",
        "http://proxy2.example:8080",
    ]


@pytest.mark.unit
def test_proxy_from_default_app_config_yaml():
    """Real configs/app_config.yaml loads proxy with enabled false."""
    cfg = get_config()
    assert cfg.proxy.enabled is False
    assert cfg.proxy.url is None
    assert cfg.proxy.rotation_strategy == "round_robin"
    assert cfg.proxy.pool == []


@pytest.mark.unit
def test_cloudflare_bypass_enabled_in_default_app_config_yaml():
    """Real configs/app_config.yaml ships the bypass ON: OLX always-bypass +
    auto-fallback for other Cloudflare-gated providers (BIN-247)."""
    cfg = get_config()
    bypass = cfg.scraping.cloudflare_bypass
    assert bypass.enabled is True
    assert bypass.platforms == ["olx"]
    assert bypass.auto_fallback is True


@pytest.mark.unit
def test_ai_stack_from_default_app_config_yaml():
    """Real configs/app_config.yaml uses qwen2.5vl + bge-m3 + num_ctx (BIN-73)."""
    cfg = get_config()
    assert cfg.ai.visual_model == "qwen2.5vl:7b"
    assert cfg.ai.text_model == "qwen2.5vl:7b"
    assert cfg.ai.embedding_model == "bge-m3"
    assert cfg.ai.num_ctx == 16384
    # BIN-248: Gemma backfill model + image downscaling defaults.
    assert cfg.ai.gemma_model == "gemma-4-31b-it"
    assert cfg.ai.image_max_dimension == 768
    # DW-7: the transport-storm quota window ships enabled (0 would disable it).
    assert cfg.ai.gemini_transport_quota_window_seconds == 300.0


@pytest.mark.unit
def test_ai_rejects_a_negative_transport_quota_window():
    """A negative window is meaningless — ``0`` is the documented "off" value.

    Silently accepting one would make the recency test always false, disabling
    the DW-7 inference with no signal to the operator.
    """
    from src.infra.config import AIConfig

    with pytest.raises(ValidationError):
        AIConfig(gemini_transport_quota_window_seconds=-1.0)

    # ``0`` is legal and is how an operator turns the inference off.
    off = AIConfig(gemini_transport_quota_window_seconds=0.0)
    assert off.gemini_transport_quota_window_seconds == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("value", [3600.1, float("inf"), float("nan")])
def test_ai_rejects_an_unbounded_transport_quota_window(value):
    """A day-wide (or infinite) window would suppress row errors indefinitely.

    One observed 429 licenses the DW-7 inference for the whole window, so an
    unbounded one turns a dead key or a firewall change into permanent silent
    back-off instead of hard errors.
    """
    from src.infra.config import AIConfig

    with pytest.raises(ValidationError):
        AIConfig(gemini_transport_quota_window_seconds=value)

    at_ceiling = AIConfig(gemini_transport_quota_window_seconds=3600.0)
    assert at_ceiling.gemini_transport_quota_window_seconds == 3600.0


@pytest.mark.unit
def test_gemini_client_default_window_mirrors_the_config_default():
    """The client's fallback constant claims to mirror config — pin the claim.

    Both are ``300.0`` in two files; without this, changing one silently makes a
    hand-built client behave unlike every configured one.
    """
    from src.adapters.ai.client import GeminiClient
    from src.infra.config import AIConfig

    assert (
        GeminiClient._DEFAULT_TRANSPORT_QUOTA_WINDOW_SECONDS
        == AIConfig().gemini_transport_quota_window_seconds
    )
    # The client clamps a hand-built value to the same ceiling the schema
    # enforces, so the two bounds must not drift apart either.
    assert GeminiClient._MAX_TRANSPORT_QUOTA_WINDOW_SECONDS == 3600.0
    with pytest.raises(ValidationError):
        AIConfig(
            gemini_transport_quota_window_seconds=(
                GeminiClient._MAX_TRANSPORT_QUOTA_WINDOW_SECONDS + 1.0
            )
        )


@pytest.mark.unit
def test_enrichment_routing_default_all_local():
    """Shipped config routes every task class to a LOCAL backend (all-local)."""
    cfg = get_config()
    routing = cfg.ai.enrichment_routing
    assert set(routing) == {tc.value for tc in EnrichmentTaskClass}
    local_values = {b.value for b in (EnrichmentBackend.OLLAMA, EnrichmentBackend.LMSTUDIO)}
    for task_class in EnrichmentTaskClass:
        assert routing[task_class.value] in local_values


@pytest.mark.unit
def test_enrichment_routing_unknown_backend_raises(tmp_path: Path):
    """A routing value that is not a known backend fails validation."""
    yaml_content = _yaml_with_ai("""\
  enrichment_routing:
    visual: frobnicate
""")
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_enrichment_routing_unknown_task_class_raises(tmp_path: Path):
    """A routing key that is not a known task class fails validation."""
    yaml_content = _yaml_with_ai("""\
  enrichment_routing:
    frobnicate: ollama
""")
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_enrichment_routing_cloud_value_allowed(tmp_path: Path):
    """Cloud backends ARE allowed as routing values (backfill-eligible)."""
    yaml_content = _yaml_with_ai("""\
  enrichment_routing:
    visual: ollama
    sentiment: gemma
    deal_verdict: ollama
    valuation: ollama
    embedding: ollama
""")
    cfg = load_config(_write_yaml(tmp_path, yaml_content))
    assert cfg.ai.enrichment_routing["sentiment"] == "gemma"


@pytest.mark.unit
def test_enrichment_routing_partial_map_raises(tmp_path: Path):
    """A routing map that omits task classes fails validation (must be total)."""
    yaml_content = _yaml_with_ai("""\
  enrichment_routing:
    visual: ollama
""")
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_backend_cloud_scalar_raises(tmp_path: Path):
    """Legacy cloud scalar ai.backend (gemini/gemma) is rejected on the live path."""
    for cloud in ("gemini", "gemma"):
        yaml_content = _yaml_with_ai(f"  backend: {cloud}\n")
        with pytest.raises(ConfigError, match="Configuration validation failed"):
            load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_backend_unknown_scalar_raises(tmp_path: Path):
    """An unknown ai.backend value fails validation."""
    yaml_content = _yaml_with_ai("  backend: frob\n")
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_backend_local_scalar_loads(tmp_path: Path):
    """A local ai.backend value (lmstudio) loads clean."""
    yaml_content = _yaml_with_ai("  backend: lmstudio\n")
    cfg = load_config(_write_yaml(tmp_path, yaml_content))
    assert cfg.ai.backend == "lmstudio"


@pytest.mark.unit
def test_backfill_from_default_app_config_yaml():
    """Real configs/app_config.yaml exposes the BIN-248 backfill budget."""
    cfg = get_config()
    assert cfg.backfill.daily_request_budget == 14000
    assert cfg.backfill.requests_per_property == 3
    assert cfg.backfill.tpm_limit == 16000
    assert cfg.backfill.redis_prefix == "backfill:gemma"
    # BIN-269: RPM ceiling + parallelism.
    assert cfg.backfill.rpm_limit == 30
    assert cfg.backfill.concurrency == 1
    # v0.13-fu2: measured per-property token cost + TPM headroom.
    assert cfg.backfill.tokens_per_property == 7000
    assert cfg.backfill.tpm_safety_margin == 0.9
    # v0.13-s1.3: single-instance lease + operator control poll interval.
    assert cfg.backfill.lease_ttl_seconds == 900
    assert cfg.backfill.control_poll_seconds == 2.0
    # Bounded back-off for a provider 429 that is not the daily (RPD) ceiling.
    assert cfg.backfill.quota_backoff_seconds == 900


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    [
        ("lease_ttl_seconds", 10),      # shorter than the renew cadence
        # Renewal rides on row completions, so a TTL under the worst-case
        # single-property latency expires under a live run — the exact failure
        # the lease exists to prevent. The old ge=30 floor allowed it.
        ("lease_ttl_seconds", 60),
        ("control_poll_seconds", 0.0),  # busy-spins the paused loop on Redis
        ("control_poll_seconds", -1.0),
        ("quota_backoff_seconds", -1),
        # ``0`` reads as "no cap" but means *no back-off at all*: a provider
        # refusal becomes a tight retry loop against a throttled account.
        ("quota_backoff_seconds", 0),
    ],
)
def test_backfill_rejects_out_of_range_pacing_values(field, value):
    """These are pacing knobs against a live provider — bad values are refused."""
    from src.infra.config import BackfillConfig

    with pytest.raises(ValidationError):
        BackfillConfig(**{field: value})


@pytest.mark.unit
def test_backfill_control_poll_must_stay_well_under_the_lease_ttl():
    """The lease is renewed once per poll, so the *ratio* is what matters.

    Each field passed its own floor here, but a poll that slow lets the lease
    expire under a paused (or budget-waiting) runner and a second one start.
    """
    from src.infra.config import BackfillConfig

    with pytest.raises(ValidationError):
        BackfillConfig(lease_ttl_seconds=300, control_poll_seconds=200.0)

    # The shipped defaults are comfortably inside the ratio.
    assert BackfillConfig().control_poll_seconds < BackfillConfig().lease_ttl_seconds / 3


@pytest.mark.unit
def test_dedup_from_default_app_config_yaml():
    """Real configs/app_config.yaml loads dedup thresholds used by scrape_listings."""
    cfg = get_config()
    assert cfg.dedup.radius_m == 50.0
    assert cfg.dedup.area_tolerance_m2 == 2.0
    assert cfg.dedup.text_similarity_threshold == 0.65
    assert cfg.dedup.text_similarity_algorithm == "jaro_winkler"


@pytest.mark.unit
def test_osm_amenities_from_default_app_config_yaml():
    """Real configs/app_config.yaml loads OSM amenity refresh defaults (BIN-88)."""
    cfg = get_config()
    osm = cfg.neighbourhood_quality.osm_amenities
    assert osm.enabled is False
    assert osm.mode == "geojson"
    assert osm.category_targets["shop"] == 3.0
    assert osm.interval_hours == 168.0


@pytest.mark.unit
def test_transit_beat_from_default_app_config_yaml():
    """Real configs/app_config.yaml loads transit beat defaults (BIN-118)."""
    cfg = get_config()
    transit = cfg.neighbourhood_quality.transit
    assert transit.enabled is False
    assert transit.gtfs_dirs == []
    assert transit.osm_geojson_paths == []
    assert transit.interval_hours == 168.0


@pytest.mark.unit
def test_neighbourhood_access_from_default_app_config_yaml():
    """Real configs/app_config.yaml loads BIN-90 hubs and routing defaults."""
    cfg = get_config()
    access = cfg.neighbourhood_access
    assert access.enabled is True
    assert access.interval_minutes == 1440
    assert access.base_url == ""
    assert access.mode == "driving"
    assert access.max_minutes == 45.0
    assert access.avg_speed_kmh == 30.0
    bh = access.hubs["Belo Horizonte"]
    assert {h.id for h in bh} == {"praca-sete", "savassi"}
    assert access.hubs["São Paulo"][0].id == "paulista"
    assert access.hubs["Campinas"][0].id == "centro"


@pytest.mark.unit
def test_neighbourhood_access_defaults_when_absent(tmp_path: Path):
    """Missing neighbourhood_access block still exposes defaults."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)
    assert cfg.neighbourhood_access.enabled is True
    assert cfg.neighbourhood_access.hubs == {}


@pytest.mark.unit
def test_dedup_defaults_when_absent(tmp_path: Path):
    """Missing dedup block still exposes DedupConfig defaults."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    cfg = load_config(cfg_file)
    assert cfg.dedup.radius_m == 50.0
    assert cfg.dedup.text_similarity_threshold == 0.65


@pytest.mark.unit
def test_dedup_yaml_overrides(tmp_path: Path):
    yaml_content = MINIMAL_YAML + """\
dedup:
  radius_m: 25.0
  area_tolerance_m2: 4.0
  text_similarity_threshold: 0.8
  text_similarity_algorithm: token_sort
"""
    cfg = load_config(_write_yaml(tmp_path, yaml_content))
    assert cfg.dedup.radius_m == 25.0
    assert cfg.dedup.area_tolerance_m2 == 4.0
    assert cfg.dedup.text_similarity_threshold == 0.8
    assert cfg.dedup.text_similarity_algorithm == "token_sort"


# Critical YAML sections that scrape_listings / workers consume. If a section is
# present in app_config.yaml but missing from AppConfig.model_fields, Pydantic
# silently drops it and tasks blow up at runtime (see DedupConfig regression).
_CRITICAL_APP_CONFIG_SECTIONS = (
    "dedup",
    "proxy",
    "scraping",
    "scoring",
    "alerts",
    "auth",
    "ai",
    "database",
    "pipeline_metrics",
    "neighbourhood_quality",
    "neighbourhood_access",
    "ui",
)


@pytest.mark.unit
def test_critical_yaml_sections_are_appconfig_fields():
    """YAML critical sections must be declared on AppConfig (no silent drop)."""
    import yaml

    from src.infra.config import AppConfig

    repo_root = Path(__file__).resolve().parents[3]
    raw = yaml.safe_load((repo_root / "configs" / "app_config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    model_fields = set(AppConfig.model_fields)
    missing = [s for s in _CRITICAL_APP_CONFIG_SECTIONS if s in raw and s not in model_fields]
    assert missing == [], (
        f"app_config.yaml has sections not on AppConfig (would be silently ignored): {missing}"
    )
    for section in _CRITICAL_APP_CONFIG_SECTIONS:
        assert section in model_fields, f"AppConfig missing required field {section!r}"


@pytest.mark.unit
def test_scrape_listings_dedup_leaves_on_real_config():
    """scrape_listings reads these DedupConfig leaves — they must exist on get_config()."""
    cfg = get_config()
    assert isinstance(cfg.dedup.radius_m, float)
    assert isinstance(cfg.dedup.area_tolerance_m2, float)
    assert isinstance(cfg.dedup.text_similarity_threshold, float)
    assert isinstance(cfg.dedup.text_similarity_algorithm, str)
    assert cfg.dedup.text_similarity_algorithm


@pytest.mark.unit
def test_critical_section_helper_flags_missing_model_field():
    """Document the silent-drop failure mode: YAML key absent from model_fields."""
    pretend_yaml_keys = {"dedup", "proxy", "scraping"}
    pretend_model_fields = {"proxy", "scraping"}  # dedup dropped from model
    missing = [
        s
        for s in _CRITICAL_APP_CONFIG_SECTIONS
        if s in pretend_yaml_keys and s not in pretend_model_fields
    ]
    assert missing == ["dedup"]


@pytest.mark.unit
def test_proxy_invalid_rotation_strategy_raises(tmp_path: Path):
    """Unknown rotation_strategy fails AppConfig validation."""
    yaml_content = MINIMAL_YAML + """\
proxy:
  enabled: true
  rotation_strategy: zigzag
  pool: []
"""
    cfg_file = _write_yaml(tmp_path, yaml_content)

    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(cfg_file)


@pytest.mark.unit
def test_proxy_imoveis_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_PROXY__ENABLED overrides proxy.enabled."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_PROXY__ENABLED", "true")

    cfg = load_config(cfg_file)

    assert cfg.proxy.enabled is True


@pytest.mark.unit
def test_ui_locale_defaults(tmp_path: Path):
    """Absent ui: section yields en default and supported list."""
    cfg = load_config(_write_yaml(tmp_path, MINIMAL_YAML))
    assert cfg.ui.locale == "en"
    assert list(cfg.ui.supported_locales) == ["en", "pt-BR"]


@pytest.mark.unit
def test_ui_locale_from_yaml(tmp_path: Path):
    """YAML ui.locale is parsed into UiConfig."""
    yaml_content = MINIMAL_YAML + """\
ui:
  locale: pt-BR
  supported_locales:
    - en
    - pt-BR
"""
    cfg = load_config(_write_yaml(tmp_path, yaml_content))
    assert cfg.ui.locale == "pt-BR"
    assert "pt-BR" in cfg.ui.supported_locales


@pytest.mark.unit
def test_ui_locale_invalid_raises(tmp_path: Path):
    """Unknown ui.locale fails AppConfig validation."""
    yaml_content = MINIMAL_YAML + """\
ui:
  locale: fr
"""
    with pytest.raises(ConfigError, match="Configuration validation failed"):
        load_config(_write_yaml(tmp_path, yaml_content))


@pytest.mark.unit
def test_ui_locale_imoveis_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """IMOVEIS_UI__LOCALE overrides ui.locale."""
    cfg_file = _write_yaml(tmp_path, MINIMAL_YAML)
    monkeypatch.setenv("IMOVEIS_UI__LOCALE", "pt-BR")

    cfg = load_config(cfg_file)

    assert cfg.ui.locale == "pt-BR"


@pytest.mark.unit
def test_real_config_exposes_ui_locale():
    """Committed app_config.yaml must expose ui.locale for SPA preference."""
    cfg = get_config()
    assert cfg.ui.locale in ("en", "pt-BR")
    assert "en" in cfg.ui.supported_locales
    assert "pt-BR" in cfg.ui.supported_locales


@pytest.mark.unit
def test_cors_origins_defaults(tmp_path: Path):
    """Absent api: section yields the pre-BIN-136 hardcoded allowlist as default."""
    cfg = load_config(_write_yaml(tmp_path, MINIMAL_YAML))
    assert cfg.api.cors_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]


@pytest.mark.unit
def test_cors_origins_from_yaml(tmp_path: Path):
    """YAML api.cors_origins overrides the default allowlist."""
    yaml_content = MINIMAL_YAML + """\
api:
  cors_origins:
    - https://staging.example.com
    - https://app.example.com
"""
    cfg = load_config(_write_yaml(tmp_path, yaml_content))
    assert cfg.api.cors_origins == [
        "https://staging.example.com",
        "https://app.example.com",
    ]


@pytest.mark.unit
def test_api_config_is_frozen(tmp_path: Path):
    """ApiConfig, like other config sections, must be immutable."""
    cfg = load_config(_write_yaml(tmp_path, MINIMAL_YAML))
    with pytest.raises((ValidationError, AttributeError)):
        cfg.api.cors_origins = ["http://evil.example.com"]  # type: ignore[misc]


@pytest.mark.unit
def test_real_config_exposes_cors_origins():
    """Committed app_config.yaml must expose api.cors_origins for main.py CORS setup."""
    cfg = get_config()
    assert isinstance(cfg.api.cors_origins, list)
    assert cfg.api.cors_origins
    assert all(isinstance(origin, str) for origin in cfg.api.cors_origins)
