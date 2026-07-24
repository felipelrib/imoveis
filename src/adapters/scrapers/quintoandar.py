"""
QuintoAndar scraper implementation.
Uses HTML parsing to extract the Next.js `__NEXT_DATA__` state, bypassing the need for complex API anti-bot tokens.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator

from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from adapters.scrapers.registry import ScraperRegistry
from core.exceptions import CircuitBreakerOpenError
from infra.logging import get_logger

logger = get_logger(__name__)


@ScraperRegistry.register("quintoandar")
class QuintoAndarScraper(BaseScraper):
    """Scrapes properties from QuintoAndar using page iteration."""

    def __init__(self, platform_name: str, config: Dict[str, Any]):
        super().__init__(platform_name, config)
        self.city_slug = config.get("extra", {}).get("city_slug", "belo-horizonte-mg-brasil")

    def start(self) -> None:
        self.session = self.create_http_session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "max-age=0",
            }
        )
        self._cb = RedisCircuitBreaker(platform="quintoandar", failure_threshold=5, cooldown_seconds=120)

    def close(self) -> None:
        if hasattr(self, "session") and self.session is not None:
            self.session.close()

    def _throttled_request(self, method: str, url: str, **kwargs):
        import random
        import time

        if self._cb.is_open():
            raise CircuitBreakerOpenError(
                f"QuintoAndar circuit breaker is open — skipping {url}"
            )

        # Optional basic throttle
        time.sleep(random.uniform(1.0, 2.5))
        response = self.session.request(method, url, **kwargs)

        # Track success/failure for circuit breaker
        if 200 <= response.status_code < 300:
            self._cb.record_success()
        elif response.status_code >= 500 or response.status_code == 429:
            self._cb.record_failure()
        return response

    def fetch_pages(self, checkpoint: Any = None) -> Iterator[Dict[str, Any]]:
        """Fetch properties using a dynamic sliding price window to bypass pagination."""
        import collections

        queue = collections.deque(self._initial_price_windows(checkpoint))
        visited_urls = set()
        while queue:
            action, min_p, max_p = queue.popleft()
            url = f"https://www.quintoandar.com.br/{action}/imovel/{self.city_slug}/de-{min_p}-a-{max_p}-reais"
            if url in visited_urls:
                continue
            visited_urls.add(url)
            valid_houses = self._fetch_window_houses(url, action, min_p, max_p)
            if not valid_houses:
                continue
            if self._split_window(queue, action, min_p, max_p, valid_houses):
                continue
            for house_data in valid_houses.values():
                house_data["price_query_min"] = min_p
                house_data["price_query_max"] = max_p
                yield house_data

    @staticmethod
    def _initial_price_windows(checkpoint: Any) -> list[tuple[str, int, int]]:
        scrape_type = checkpoint.get("scrape_type", "both") if isinstance(checkpoint, dict) else "both"
        windows = {"alugar": (500, 15000), "comprar": (100000, 5000000)}
        rent_actions = ["alugar"] if scrape_type in ("rent", "both") else []
        sale_actions = ["comprar"] if scrape_type in ("sale", "both") else []
        actions = rent_actions + sale_actions
        return [(action, *windows[action]) for action in actions]

    def _fetch_window_houses(self, url: str, action: str, min_p: int, max_p: int) -> dict:
        logger.info("quintoandar_fetching_price_window", action=action, min_p=min_p, max_p=max_p)
        response = self._throttled_request("GET", url)
        if response.status_code != 200:
            logger.error("quintoandar_http_error", status_code=response.status_code, text=response.text[:200])
            return {}
        script = BeautifulSoup(response.text, "html.parser").find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.warning("quintoandar_no_next_data", url=url)
            return {}
        try:
            houses = json.loads(script.string)["props"]["pageProps"]["initialState"].get("houses", {})
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("quintoandar_parse_error")
            return {}
        valid_houses = {key: value for key, value in houses.items() if isinstance(value, dict)}
        if not valid_houses:
            logger.debug("quintoandar_no_houses_in_window", min_p=min_p, max_p=max_p)
        return valid_houses

    @staticmethod
    def _split_window(queue, action: str, min_p: int, max_p: int, houses: dict) -> bool:
        if len(houses) < 12 or min_p >= max_p:
            return False
        mid = (min_p + max_p) // 2
        if mid <= min_p:
            return False
        queue.extend(((action, min_p, mid), (action, mid + 1, max_p)))
        logger.info("quintoandar_splitting_window", min_p=min_p, max_p=max_p, mid=mid, houses_found=len(houses))
        return True

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert QuintoAndar JSON into our internal PropertyCandidate format."""
        neighbourhood = raw.get("neighbourhood")
        address_str = self._format_address(raw.get("address", {}), neighbourhood)
        image_urls = self._image_urls(raw.get("photos", []))
        rent_price, sale_price, condo_fee, iptu, fees_bundled, fees_note, partial = self._prices_and_fees(raw)
        is_rent = rent_price > 0
        is_sale = sale_price > 0
        price = rent_price if is_rent else sale_price
        if price <= 0:
            raise ValueError(f"Invalid price: {price}")
        location_dict = self._location(raw.get("location", {}))
        listings = self._listings(raw, rent_price, sale_price, condo_fee, iptu, fees_bundled, fees_note, partial)

        # Build property candidate
        return {
            "platform": "quintoandar",
            "platform_id": str(raw.get("id", "")),
            "title": raw.get("type", "Imóvel") + f" em {neighbourhood or 'Belo Horizonte'}",
            "description": raw.get("description", ""),
            "price": price,
            "area_m2": float(raw.get("area") or 0.0),
            "bedrooms": int(raw.get("bedrooms") or 0),
            "bathrooms": int(raw.get("bathrooms") or 0),
            "parking": int(raw.get("parkingSpots") or raw.get("parkingSpaces") or 0),
            "location": location_dict,
            "address": address_str,
            "image_urls": image_urls,
            "props_json": {
                "type": raw.get("type"),
                "condo_fee": condo_fee,
                "iptu": iptu,
                "fees_bundled": fees_bundled or None,
                "isFurnished": raw.get("isFurnished"),
                "neighborhood": neighbourhood,
                "amenities": (raw.get("amenities") or []) + (raw.get("installations") or []),
                "available_for_rent": is_rent,
                "available_for_sale": is_sale,
            },
            "listings": listings,
        }

    @staticmethod
    def _format_address(address: dict, neighbourhood: str | None) -> str:
        parts = [address.get("address"), neighbourhood, address.get("city")]
        return ", ".join(part for part in parts if part) or "Endereço não disponível"

    @staticmethod
    def _image_urls(photos: list) -> list[str]:
        urls = []
        for photo in photos:
            if isinstance(photo, str):
                value = photo
            elif isinstance(photo, dict):
                value = photo.get("url") or photo.get("imagePath")
            else:
                value = None
            if value:
                urls.append(value if value.startswith("http") else f"https://www.quintoandar.com.br/img/{value}")
        return urls

    def _prices_and_fees(self, raw: dict) -> tuple:
        partial, sale = float(raw.get("rentPrice") or 0), float(raw.get("salePrice") or 0)
        condo, iptu, bundled, note = self._extract_fees(raw)
        total_cost = raw.get("totalCost")
        rent = float(total_cost) if total_cost not in (None, "", 0, 0.0) else partial + (condo or 0) + (iptu or 0)
        if condo is None and iptu is None and partial > 0 and rent > partial:
            condo, bundled, note = round(rent - partial, 2), True, "condo+IPTU derived from totalCost - rentPrice"
        return rent, sale, condo, iptu, bundled, note, partial

    @staticmethod
    def _location(location: dict) -> dict | None:
        lat, lon = location.get("lat"), location.get("lon", location.get("lng"))
        return {"lat": float(lat), "lon": float(lon)} if lat is not None and lon is not None else None

    @staticmethod
    def _listings(raw, rent, sale, condo, iptu, bundled, note, partial) -> list[dict]:
        base = {
            "platform": "quintoandar", "platform_listing_id": str(raw.get("id", "")), "currency": "BRL",
            "url": f"https://www.quintoandar.com.br/imovel/{raw.get('id', '')}",
            "is_furnished": raw.get("isFurnished"), "condo_fee": condo, "iptu": iptu,
        }

        def listing(kind, price, partial_price):
            details = {"partial_price": partial_price}
            if bundled:
                details["fees_bundled"] = True
            if note:
                details["fees_note"] = note
            return {**base, "listing_type": kind, "price": price, "raw_json": details}
        return [listing(kind, price, source_price) for kind, price, source_price in
                (("rent", rent, partial), ("sale", sale, sale)) if price > 0]

    @staticmethod
    def _positive_float(value: Any) -> float | None:
        """Parse a fee value; return None when missing or non-positive."""
        if value is None or value == "":
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _extract_fees(self, raw: Dict[str, Any]) -> tuple[float | None, float | None, bool, str | None]:
        """Extract condo / IPTU from QuintoAndar search or detail JSON.

        Prefer separate condoFee + iptu. Fall back to bundled condoIptu as condo_fee
        (IPTU unknown). Unknown fees stay None (not 0.0) so the UI can show '—'.
        """
        condo_separate = self._positive_float(raw.get("condoFee"))
        iptu = self._positive_float(raw.get("iptu"))
        condo_iptu = self._positive_float(raw.get("condoIptu"))

        if condo_separate is not None or iptu is not None:
            return condo_separate, iptu, False, None

        if condo_iptu is not None:
            return condo_iptu, None, True, "condoIptu is a bundled condo+IPTU field"

        return None, None, False, None
