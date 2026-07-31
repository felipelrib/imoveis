"""FlareSolverr-backed HTTP session for Cloudflare-gated scrapers (BIN-246).

OLX serves a Cloudflare JS challenge (HTTP 403) to plain HTTP clients, but a real
browser from a residential IP clears it. `FlareSolverr
<https://github.com/FlareSolverr/FlareSolverr>`_ runs that browser as a sidecar
service: POST ``{cmd: "request.get", url}`` to its ``/v1`` endpoint and it returns
the solved page HTML.

``FlareSolverrSession`` is a drop-in for the subset of ``httpx.Client`` the
scrapers use — ``.get(url)`` (returning a real ``httpx.Response`` so
``status_code`` / ``text`` / ``url`` all work), ``.headers``, and ``.close()`` —
so a platform scraper needs no changes beyond receiving this session instead of a
raw ``httpx.Client``. Throttling and circuit-breaker logic stay in the scraper's
``_throttled_request``; only the transport swaps.
"""

from __future__ import annotations

from typing import Any

import httpx

from infra.config import CloudflareBypassConfig
from infra.logging import get_logger

logger = get_logger(__name__)


class FlareSolverrError(RuntimeError):
    """Raised when the FlareSolverr service errors or returns no solution."""


class FlareSolverrSession:
    """Route scraper GETs through a FlareSolverr sidecar.

    Parameters
    ----------
    config:
        The resolved :class:`CloudflareBypassConfig` (endpoint + timeout).
    headers:
        The headers mapping from the httpx client it replaces, kept so callers
        that do ``session.headers.update(...)`` still work (FlareSolverr drives
        its own browser UA, so these are advisory only).
    client:
        Optional injected ``httpx.Client`` (tests); one is created otherwise.
    """

    def __init__(
        self,
        config: CloudflareBypassConfig,
        *,
        headers: Any = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self.headers = headers if headers is not None else httpx.Headers()
        # Allow the browser solve (max_timeout_ms) plus network overhead.
        timeout = config.max_timeout_ms / 1000.0 + 15.0
        self._client = client or httpx.Client(timeout=timeout)

    def get(self, url: str, follow_redirects: bool = True) -> httpx.Response:
        """Solve ``url`` via FlareSolverr and return an ``httpx.Response``.

        ``follow_redirects`` is accepted for signature compatibility;
        FlareSolverr follows redirects inside the browser regardless.
        """
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self._config.max_timeout_ms,
        }
        request = httpx.Request("GET", url)
        try:
            resp = self._client.post(self._config.endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FlareSolverrError(f"FlareSolverr request failed: {exc}") from exc

        if data.get("status") != "ok":
            raise FlareSolverrError(
                f"FlareSolverr did not solve {url}: {data.get('message') or data.get('status')}"
            )
        solution = data.get("solution") or {}
        status_code = int(solution.get("status") or 0)
        html = solution.get("response") or ""
        final_url = solution.get("url") or url
        logger.info(
            "flaresolverr_fetch",
            url=url,
            final_url=final_url,
            status_code=status_code,
            bytes=len(html),
        )
        return httpx.Response(status_code=status_code, text=html, request=request)

    def close(self) -> None:
        self._client.close()
