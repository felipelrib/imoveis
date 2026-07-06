"""Unit tests for the centralized config loader."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from infra.config import AppConfig, ScoringConfig, load_config, DedupeConfig


def test_load_config_from_yaml(tmp_path: Path):
    yaml_content = """
database:
  url: postgresql://test:test@localhost/testdb
redis_url: redis://localhost:6379/1
dedup:
  radius_m: 100.0
  text_similarity_threshold: 0.7
scoring:
  stat_weight: 0.7
  ai_weight: 0.3
ai:
  backend: ollama
  default_model: qwen2-vl
"""
    cfg_file = tmp_path / "app_config.yaml"
    cfg_file.write_text(yaml_content)

    cfg = load_config(cfg_file)

    assert cfg.database_url == "postgresql://test:test@localhost/testdb"
    assert cfg.redis_url == "redis://localhost:6379/1"
    assert cfg.dedup.radius_m == 100.0
    assert cfg.dedup.text_similarity_threshold == 0.7
    assert cfg.scoring.stat_weight == 0.7
    assert cfg.ai.model == "qwen2-vl"


def test_env_var_overrides_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "app_config.yaml").write_text("database:\n  url: postgresql://from_file/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://from_env/db")

    cfg = load_config(tmp_path / "app_config.yaml")
    assert cfg.database_url == "postgresql://from_env/db"


def test_defaults_when_no_config_file():
    cfg = load_config(Path("/nonexistent/path/app_config.yaml"))
    assert isinstance(cfg, AppConfig)
    assert isinstance(cfg.dedup, DedupeConfig)
    assert isinstance(cfg.scoring, ScoringConfig)
