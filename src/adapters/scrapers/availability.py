"""Platform listing availability probes (BIN-80).

Soft-deactivation only — never treat proxy/Cloudflare failures as unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from adapters.scrapers.http_client import create_scraper_http_client
from infra.config import get_config
from infra.logging import get_logger

logger = get_logger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_OLX_LISTING_ID_RE = re.compile(r"(?:/vi/|/imoveis/[^?\s]*?-)(\d{6,})(?:\.htm)?", re.I)


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AvailabilityResult:
    status: AvailabilityStatus
    reason: str = ""


def _listing_type_to_qa_context(listing_type: str | None) -> str:
    lt = (listing_type or "").strip().lower()
    if lt in ("sale", "venda", "buy", "comprar"):
        return "SALE"
    return "RENT"


def parse_quintoandar_availability(
    *,
    status_code: int,
    html: str,
    listing_type: str | None = None,
) -> AvailabilityResult:
    """Classify a QuintoAndar detail response.

    Prefer ``__NEXT_DATA__`` listing status for the matching business context.
    HTTP 404 alone is not enough — QA still SSR's despublicado houses as 404.
    """
    if status_code in (403, 429) or status_code >= 500:
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, f"http_{status_code}")

    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        if status_code == 404:
            # Soft 404 without payload — ambiguous; keep unknown to avoid false offs.
            return AvailabilityResult(AvailabilityStatus.UNKNOWN, "qa_404_no_next_data")
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "qa_no_next_data")

    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, TypeError):
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "qa_next_data_invalid")

    house_info = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialState", {})
        .get("house", {})
        .get("houseInfo")
    )
    if not isinstance(house_info, dict):
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "qa_no_house_info")

    context = _listing_type_to_qa_context(listing_type)
    listings = house_info.get("listings")
    if isinstance(listings, list):
        for entry in listings:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("businessContext", "")).upper() != context:
                continue
            status = str(entry.get("status") or "").lower()
            if status == "publicado":
                return AvailabilityResult(AvailabilityStatus.AVAILABLE, "qa_listing_publicado")
            if status:
                return AvailabilityResult(
                    AvailabilityStatus.UNAVAILABLE,
                    f"qa_listing_{status}",
                )

    house_status = str(house_info.get("status") or "").lower()
    if house_status == "publicado":
        return AvailabilityResult(AvailabilityStatus.AVAILABLE, "qa_house_publicado")
    if house_status in ("despublicado", "unpublished", "inactive"):
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, f"qa_house_{house_status}")

    lowered = (html or "").lower()
    if "esse imóvel está indisponível" in lowered or "esse imovel esta indisponivel" in lowered:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "qa_ui_indisponivel")

    return AvailabilityResult(AvailabilityStatus.UNKNOWN, "qa_status_unclear")


def _olx_listing_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    match = _OLX_LISTING_ID_RE.search(url)
    return match.group(1) if match else None


def parse_olx_availability(
    *,
    status_code: int,
    html: str,
    request_url: str,
    final_url: str | None = None,
) -> AvailabilityResult:
    """Classify an OLX detail response."""
    if status_code in (403, 429) or status_code >= 500:
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, f"http_{status_code}")

    final = final_url or request_url or ""
    title = ""
    soup = BeautifulSoup(html or "", "html.parser")
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    title_l = title.lower()
    body_l = (html or "").lower()

    if status_code == 410:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_http_410")

    if "anúncio não encontrado" in title_l or "anuncio nao encontrado" in title_l:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_title_not_found")

    if "a página não foi encontrada" in body_l or "a pagina nao foi encontrada" in body_l:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_page_not_found")

    # Dead IDs sometimes soft-redirect to the homepage.
    parsed = urlparse(final)
    path = (parsed.path or "/").rstrip("/") or "/"
    if path in ("", "/") and "olx.com.br" in (parsed.netloc or ""):
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_redirect_homepage")

    expected_id = _olx_listing_id_from_url(request_url)
    if expected_id and expected_id not in final:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_id_lost_in_redirect")

    if 200 <= status_code < 300:
        # Active detail pages keep contact CTAs / price; require listing id still present.
        if expected_id and expected_id in final:
            return AvailabilityResult(AvailabilityStatus.AVAILABLE, "olx_http_ok")
        if expected_id is None and status_code == 200:
            return AvailabilityResult(AvailabilityStatus.AVAILABLE, "olx_http_ok_no_id")

    if status_code == 404:
        return AvailabilityResult(AvailabilityStatus.UNAVAILABLE, "olx_http_404")

    return AvailabilityResult(AvailabilityStatus.UNKNOWN, f"olx_http_{status_code}")


def classify_response(
    platform: str,
    *,
    status_code: int,
    html: str,
    request_url: str,
    final_url: str | None = None,
    listing_type: str | None = None,
) -> AvailabilityResult:
    """Dispatch to the platform-specific classifier."""
    name = (platform or "").strip().lower()
    if name in ("quintoandar", "qa"):
        return parse_quintoandar_availability(
            status_code=status_code,
            html=html,
            listing_type=listing_type,
        )
    if name == "olx":
        return parse_olx_availability(
            status_code=status_code,
            html=html,
            request_url=request_url,
            final_url=final_url,
        )
    return AvailabilityResult(AvailabilityStatus.UNKNOWN, f"unsupported_platform:{name}")


def check_listing(
    platform: str,
    url: str,
    listing_type: str | None = None,
    *,
    client: httpx.Client | None = None,
    timeout: float | None = None,
) -> AvailabilityResult:
    """HTTP GET ``url`` and classify availability for ``platform``."""
    if not url:
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "missing_url")

    cfg = get_config()
    timeout_sec = (
        float(timeout)
        if timeout is not None
        else float(cfg.scraping.availability_recheck.request_timeout_sec)
    )
    owns_client = client is None
    http = client or create_scraper_http_client(
        timeout=timeout_sec,
        follow_redirects=True,
        headers={"User-Agent": cfg.scraping.user_agent},
    )
    try:
        response = http.get(url, timeout=timeout_sec)
        return classify_response(
            platform,
            status_code=response.status_code,
            html=response.text or "",
            request_url=url,
            final_url=str(response.url),
            listing_type=listing_type,
        )
    except httpx.TimeoutException:
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "timeout")
    except httpx.HTTPError as exc:
        logger.warning("availability_http_error", platform=platform, url=url, error=str(exc))
        return AvailabilityResult(AvailabilityStatus.UNKNOWN, "http_error")
    finally:
        if owns_client:
            http.close()


def deactivate_listing_and_maybe_property(session: Any, listing_id: str) -> dict[str, Any]:
    """Set listing inactive; deactivate property when no active listings remain.

    Returns a summary dict for logging / telemetry.
    """
    from sqlalchemy import text

    session.execute(
        text(
            "UPDATE property_listings SET active = false "
            "WHERE id = :id AND active = true"
        ),
        {"id": listing_id},
    )
    row = session.execute(
        text(
            "SELECT property_id FROM property_listings WHERE id = :id"
        ),
        {"id": listing_id},
    ).fetchone()
    if not row:
        return {"listing_id": listing_id, "property_deactivated": False}

    property_id = str(row[0])
    remaining = session.execute(
        text(
            "SELECT count(*) FROM property_listings "
            "WHERE property_id = :pid AND active = true"
        ),
        {"pid": property_id},
    ).scalar()
    property_deactivated = False
    if int(remaining or 0) == 0:
        session.execute(
            text(
                "UPDATE properties SET active = false "
                "WHERE id = :pid AND active = true"
            ),
            {"pid": property_id},
        )
        property_deactivated = True

    return {
        "listing_id": listing_id,
        "property_id": property_id,
        "property_deactivated": property_deactivated,
        "remaining_active_listings": int(remaining or 0),
    }
