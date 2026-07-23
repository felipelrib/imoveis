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
        import httpx

        proxy = self.config.get("extra", {}).get("proxy")
        self.session = httpx.Client(proxy=proxy)
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
        if not isinstance(checkpoint, dict):
            checkpoint = {}

        scrape_type = checkpoint.get("scrape_type", "both")

        actions = []
        if scrape_type in ("rent", "both"):
            actions.append("alugar")
        if scrape_type in ("sale", "both"):
            actions.append("comprar")

        import collections

        queue = collections.deque()

        for action in actions:
            if action == "alugar":
                queue.append((action, 500, 15000))
            else:
                queue.append((action, 100000, 5000000))

        visited_urls = set()

        while queue:
            action, min_p, max_p = queue.popleft()

            # e.g., https://www.quintoandar.com.br/alugar/imovel/belo-horizonte-mg-brasil/de-1000-a-1200-reais
            url = f"https://www.quintoandar.com.br/{action}/imovel/{self.city_slug}/de-{min_p}-a-{max_p}-reais"

            if url in visited_urls:
                continue
            visited_urls.add(url)

            logger.info(
                "quintoandar_fetching_price_window",
                action=action,
                min_p=min_p,
                max_p=max_p,
            )
            response = self._throttled_request("GET", url)

            if response.status_code != 200:
                logger.error(
                    "quintoandar_http_error",
                    status_code=response.status_code,
                    text=response.text[:200],
                )
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            script = soup.find("script", id="__NEXT_DATA__")

            if not script:
                logger.warning("quintoandar_no_next_data", url=url)
                continue

            try:
                data = json.loads(script.string)
                state = data["props"]["pageProps"]["initialState"]
                houses = state.get("houses", {})
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error("quintoandar_parse_error", error=str(exc))
                continue

            # Filter valid house dictionaries
            valid_houses = {k: v for k, v in houses.items() if isinstance(v, dict)}

            # If we hit 12 or more houses and we can still split the price range, split and requeue
            if len(valid_houses) >= 12 and min_p < max_p:
                mid = (min_p + max_p) // 2
                if mid > min_p:
                    queue.append((action, min_p, mid))
                    queue.append((action, mid + 1, max_p))
                    logger.info(
                        "quintoandar_splitting_window",
                        min_p=min_p,
                        max_p=max_p,
                        mid=mid,
                        houses_found=len(valid_houses),
                    )
                    continue  # Do not yield houses yet, let the smaller windows fetch them to ensure we don't miss any!

            if not valid_houses:
                logger.debug("quintoandar_no_houses_in_window", min_p=min_p, max_p=max_p)
                continue

            # Yield each house
            for property_id, house_data in valid_houses.items():
                house_data["price_query_min"] = min_p
                house_data["price_query_max"] = max_p
                yield house_data

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert QuintoAndar JSON into our internal PropertyCandidate format."""
        address_dict = raw.get("address", {})
        neighbourhood = raw.get("neighbourhood")

        # Build a full address string
        addr_parts = []
        if address_dict.get("address"):
            addr_parts.append(address_dict["address"])
        if neighbourhood:
            addr_parts.append(neighbourhood)
        if address_dict.get("city"):
            addr_parts.append(address_dict["city"])

        address_str = ", ".join(addr_parts) if addr_parts else "Endereço não disponível"

        # Extract images
        photos = raw.get("photos", [])
        image_urls = []
        for p in photos:
            if isinstance(p, str):
                image_urls.append(p if p.startswith("http") else f"https://www.quintoandar.com.br/img/{p}")
            elif isinstance(p, dict):
                url = p.get("url") or p.get("imagePath")
                if url:
                    image_urls.append(url if url.startswith("http") else f"https://www.quintoandar.com.br/img/{url}")

        # Determine price and transaction types
        rent_price_partial = float(raw.get("rentPrice") or 0.0)
        sale_price = float(raw.get("salePrice") or 0.0)

        condo_fee, iptu, fees_bundled, fees_note = self._extract_fees(raw)

        # Prefer QuintoAndar's all-in totalCost; fall back to base + fees
        if raw.get("totalCost") not in (None, "", 0, 0.0):
            rent_price = float(raw["totalCost"])
        elif rent_price_partial > 0:
            rent_price = rent_price_partial + (condo_fee or 0.0) + (iptu or 0.0)
        else:
            rent_price = 0.0

        # When search JSON only has totalCost + rentPrice, derive bundled fees from the gap
        if (
            condo_fee is None
            and iptu is None
            and rent_price_partial > 0
            and rent_price > rent_price_partial
        ):
            condo_fee = round(rent_price - rent_price_partial, 2)
            fees_bundled = True
            fees_note = "condo+IPTU derived from totalCost - rentPrice"

        is_rent = rent_price > 0
        is_sale = sale_price > 0

        # Default to rent price if available, otherwise sale price
        price = rent_price if is_rent else sale_price

        if price <= 0:
            raise ValueError(f"Invalid price: {price}")

        # Extract location
        loc = raw.get("location", {})
        lat = float(loc.get("lat") or 0.0)
        lon = float(loc.get("lon") or loc.get("lng") or 0.0)

        if lat == 0.0 and lon == 0.0:
            location_dict = None
        else:
            location_dict = {"lat": lat, "lon": lon}

        def _listing_raw_json(partial: float) -> dict:
            payload: Dict[str, Any] = {"partial_price": partial}
            if fees_bundled:
                payload["fees_bundled"] = True
            if fees_note:
                payload["fees_note"] = fees_note
            return payload

        # Create discrete listings for the dedupe engine
        listings = []
        base_url = f"https://www.quintoandar.com.br/imovel/{raw.get('id', '')}"
        if is_rent:
            listings.append(
                {
                    "platform": "quintoandar",
                    "platform_listing_id": str(raw.get("id", "")),
                    "listing_type": "rent",
                    "price": rent_price,
                    "currency": "BRL",
                    "url": base_url,
                    "is_furnished": raw.get("isFurnished"),
                    "condo_fee": condo_fee,
                    "iptu": iptu,
                    "raw_json": _listing_raw_json(rent_price_partial),
                }
            )
        if is_sale:
            listings.append(
                {
                    "platform": "quintoandar",
                    "platform_listing_id": str(raw.get("id", "")),
                    "listing_type": "sale",
                    "price": sale_price,
                    "currency": "BRL",
                    "url": base_url,
                    "is_furnished": raw.get("isFurnished"),
                    "condo_fee": condo_fee,
                    "iptu": iptu,
                    "raw_json": _listing_raw_json(sale_price),
                }
            )

        amenities = raw.get("amenities") or []
        installations = raw.get("installations") or []
        all_amenities = amenities + installations

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
            "parking": int(raw.get("parkingSpaces") or 0),
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
                "amenities": all_amenities,
                "available_for_rent": is_rent,
                "available_for_sale": is_sale,
            },
            "listings": listings,
        }

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
