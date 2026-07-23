"""Unit tests for rate limiter wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_limiter_uses_redis_url():
    cfg = MagicMock()
    cfg.redis.url = "redis://example:6379/1"
    with patch("infra.config.get_config", return_value=cfg):
        with patch("slowapi.Limiter") as limiter_cls:
            import importlib

            import infra.limiter as limiter_mod

            importlib.reload(limiter_mod)
    assert limiter_cls.call_count >= 1
    kwargs = limiter_cls.call_args.kwargs
    assert kwargs["storage_uri"] == "redis://example:6379/1"
