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

    def get(self, url: str, **_kwargs: Any) -> httpx.Response:
        """Solve ``url`` via FlareSolverr and return an ``httpx.Response``.

        Extra kwargs (e.g. ``follow_redirects=True``) are accepted for drop-in
        compatibility with ``httpx.Client.get`` and ignored — FlareSolverr always
        follows redirects inside the browser.
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


class CloudflareFallbackSession:
    """Direct httpx first; retry a Cloudflare 403 through FlareSolverr (BIN-247).

    A drop-in for the ``.get()`` / ``.headers`` / ``.close()`` subset the scrapers
    use, for platforms NOT on the always-bypass list. It issues a normal (cheap,
    fast) httpx GET and only when the response is a Cloudflare block (HTTP 403 —
    the signal the rest of the pipeline already treats as Cloudflare, see
    ``BaseScraper._record_circuit_outcome``) does it retry that request via a
    FlareSolverr solve. After the first block it is *sticky*: subsequent GETs go
    straight to FlareSolverr, so a gated provider does not pay a wasted direct
    403 (and trip its circuit breaker) on every request. Un-gated providers never
    touch FlareSolverr at all.
    """

    def __init__(
        self,
        direct: Any,
        config: CloudflareBypassConfig,
        *,
        flare: Any = None,
    ) -> None:
        self._direct = direct
        self._config = config
        # Share the direct client's headers object so ``session.headers.update``
        # in the scraper's ``start()`` reaches the real transport.
        self.headers = getattr(direct, "headers", None)
        if self.headers is None:
            self.headers = httpx.Headers()
        self._flare = flare
        self._use_flare = False

    def _flare_session(self) -> Any:
        if self._flare is None:
            self._flare = FlareSolverrSession(self._config, headers=self.headers)
        return self._flare

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        if self._use_flare:
            return self._flare_session().get(url, **kwargs)
        response = self._direct.get(url, **kwargs)
        if response.status_code != 403:
            return response
        try:
            solved = self._flare_session().get(url, **kwargs)
        except FlareSolverrError as exc:
            # Sidecar down / not deployed: degrade to the original 403 so the
            # scraper behaves exactly as it did before the bypass existed
            # (403 → handled gracefully), rather than surfacing a new error.
            logger.warning("cloudflare_autofallback_unavailable", url=url, error=str(exc))
            return response
        logger.info("cloudflare_autofallback_engaged", url=url)
        self._use_flare = True
        return solved

    def close(self) -> None:
        try:
            self._direct.close()
        finally:
            if self._flare is not None:
                self._flare.close()
