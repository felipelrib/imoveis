"""Unit tests for the shared test env-var helper (BIN-142)."""

from __future__ import annotations

from tests.env_helpers import DEFAULT_OLLAMA_HOST, get_api_key, get_ollama_host, get_redis_url


class TestGetRedisUrl:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")
        assert get_redis_url() == "redis://localhost:6379/15"

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert get_redis_url() is None


class TestGetApiKey:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "secret-value")
        assert get_api_key() == "secret-value"

    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        assert get_api_key() == ""

    def test_returns_custom_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        assert get_api_key(default="fallback") == "fallback"


class TestGetOllamaHost:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_HOST", "http://example:11434")
        assert get_ollama_host() == "http://example:11434"

    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        assert get_ollama_host() == DEFAULT_OLLAMA_HOST

    def test_returns_custom_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        assert get_ollama_host(default="http://custom:1234") == "http://custom:1234"
