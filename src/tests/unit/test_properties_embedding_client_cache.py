"""Unit coverage for the per-thread embedding-client cache added in BIN-143.

Exercises the cache-miss / cache-hit / reset branches directly with a mocked
AI client, since the existing integration test only asserts end-to-end
semantic-search behavior (not this caching logic's branches at the unit tier).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.properties import _get_embedding_client, _reset_embedding_clients


@pytest.mark.unit
class TestEmbeddingClientCache:
    def teardown_method(self):
        _reset_embedding_clients()

    def test_first_call_creates_and_caches_client(self):
        with patch("adapters.ai.client.create_ai_client") as mock_create:
            mock_create.return_value = object()
            client = _get_embedding_client()
            assert client is mock_create.return_value
            mock_create.assert_called_once()

    def test_same_thread_reuses_cached_client(self):
        with patch("adapters.ai.client.create_ai_client") as mock_create:
            mock_create.return_value = object()
            first = _get_embedding_client()
            second = _get_embedding_client()
            assert first is second
            mock_create.assert_called_once()

    def test_reset_clears_cache_and_forces_recreation(self):
        with patch("adapters.ai.client.create_ai_client") as mock_create:
            mock_create.side_effect = [object(), object()]
            first = _get_embedding_client()
            _reset_embedding_clients()
            second = _get_embedding_client()
            assert first is not second
            assert mock_create.call_count == 2

    def test_different_threads_get_different_clients(self):
        import threading

        with patch("adapters.ai.client.create_ai_client") as mock_create:
            mock_create.side_effect = lambda: object()
            main_client = _get_embedding_client()
            other_thread_client = {}

            def _in_other_thread():
                other_thread_client["client"] = _get_embedding_client()

            t = threading.Thread(target=_in_other_thread)
            t.start()
            t.join()

            assert other_thread_client["client"] is not main_client
            assert mock_create.call_count == 2
