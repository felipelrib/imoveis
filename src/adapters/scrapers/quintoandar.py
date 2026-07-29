"""
QuintoAndar scraper implementation.
Uses HTML parsing to extract the Next.js `__NEXT_DATA__` state, bypassing the need for complex API anti-bot tokens.
"""

from __future__ import annotations

import collections
import json
from typing import Any, Dict, Iterator

from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.funnel import bisect_price, listing_id_from_raw, unique_by
from adapters.scrapers.listing_description import extract_quintoandar_description
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from adapters.scrapers.registry import ScraperRegistry
from core.exceptions import CircuitBreakerOpenError
from infra.logging import get_logger

logger = get_logger(__name__)

# SSR search pages embed at most this many houses in __NEXT_DATA__; no deeper
# pagination without a non-SSR (tokenized) client. Funnel ends at price → nb → type.
_SSR_PAGE_CEILING = 12

# (action, min_p, max_p, neighborhood_slug|None, house_type|None, city_slug)
_QaWindow = tuple[str, int, int, str | None, str | None, str]

_HOUSE_TYPES = ("apartamento", "casa")

_DEFAULT_CITY_SLUG = "belo-horizonte-mg-brasil"


def _normalize_qa_property_type(raw_type: Any) -> str | None:
    from core.property_type import normalize_property_type

    return normalize_property_type(str(raw_type) if raw_type is not None else None)


def _city_state_from_slug(city_slug: str) -> tuple[str, str]:
    """Map QuintoAndar city_slug → (display city, UF) for normalize fallbacks."""
    slug = (city_slug or "").casefold()
    if "campinas" in slug:
        return "Campinas", "SP"
    if "sao-paulo" in slug:
        return "São Paulo", "SP"
    if "belo-horizonte" in slug or "-mg-" in slug:
        return "Belo Horizonte", "MG"
    return "Belo Horizonte", "MG"


@ScraperRegistry.register("quintoandar")
class QuintoAndarScraper(BaseScraper):
    """Scrapes properties from QuintoAndar using price + neighborhood funneling."""

    def __init__(self, platform_name: str, config: Dict[str, Any]):
        super().__init__(platform_name, config)
        extra = config.get("extra") or {}
        self._cities = self._parse_cities(extra)
        self.city_slug = self._cities[0]["city_slug"]
        self._city_neighborhoods = {
            c["city_slug"]: c["neighborhoods"] for c in self._cities
        }
        # Back-compat for tests that read/mutate ``_neighborhoods`` (first city).
        self._neighborhoods = list(self._city_neighborhoods[self.city_slug])
        self._price_rent = self._parse_price_pair(extra.get("price_rent"), (500, 15000))
        self._price_sale = self._parse_price_pair(extra.get("price_sale"), (100000, 5000000))
        self.ssr_truncated_windows = 0
        self.ssr_truncated_houses_yielded = 0

    @classmethod
    def _parse_cities(cls, extra: dict) -> list[dict[str, Any]]:
        raw_cities = extra.get("cities")
        if isinstance(raw_cities, list) and raw_cities:
            out: list[dict[str, Any]] = []
            for item in raw_cities:
                if not isinstance(item, dict):
                    continue
                slug = item.get("city_slug")
                if not slug:
                    continue
                out.append(
                    {
                        "city_slug": str(slug),
                        "neighborhoods": cls._parse_neighborhoods(
                            item.get("neighborhoods") or []
                        ),
                    }
                )
            if out:
                return out
        slug = str(extra.get("city_slug") or _DEFAULT_CITY_SLUG)
        return [
            {
                "city_slug": slug,
                "neighborhoods": cls._parse_neighborhoods(
                    extra.get("neighborhoods") or []
                ),
            }
        ]

    @staticmethod
    def _parse_price_pair(value: Any, default: tuple[int, int]) -> tuple[int, int]:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(v, (int, float)) for v in value)
        ):
            return int(value[0]), int(value[1])
        return default

    @staticmethod
    def _parse_neighborhoods(raw: list) -> list[str]:
        out: list[str] = []
        for item in raw:
            if isinstance(item, dict) and item.get("slug"):
                out.append(str(item["slug"]))
            elif isinstance(item, str) and item:
                out.append(item)
        return out

    def _neighborhoods_for_city(self, city_slug: str) -> list[str]:
        if city_slug in self._city_neighborhoods:
            return self._city_neighborhoods[city_slug]
        # Tests may mutate ``_neighborhoods`` without updating the map.
        if city_slug == self.city_slug:
            return self._neighborhoods
        return []

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
        """Fetch properties using price / neighborhood / house-type funneling."""
        self.ssr_truncated_windows = 0
        self.ssr_truncated_houses_yielded = 0
        queue: collections.deque[_QaWindow] = collections.deque(
            self._initial_price_windows(checkpoint)
        )
        visited_urls: set[str] = set()
        seen_ids: set[str] = set()
        while queue:
            action, min_p, max_p, nb_slug, house_type, city_slug = queue.popleft()
            url = self._window_url(
                action, min_p, max_p, nb_slug, house_type, city_slug=city_slug
            )
            if url in visited_urls:
                continue
            visited_urls.add(url)
            valid_houses = self._fetch_window_houses(url, action, min_p, max_p)
            if not valid_houses:
                continue
            if len(valid_houses) >= _SSR_PAGE_CEILING:
                if self._enqueue_price_split(
                    queue, action, min_p, max_p, nb_slug, house_type, city_slug
                ):
                    continue
                neighborhoods = self._neighborhoods_for_city(city_slug)
                if nb_slug is None and neighborhoods:
                    for slug in neighborhoods:
                        queue.append(
                            (action, min_p, max_p, slug, house_type, city_slug)
                        )
                    logger.info(
                        "quintoandar_fanout_neighborhoods",
                        action=action,
                        min_p=min_p,
                        max_p=max_p,
                        count=len(neighborhoods),
                        house_type=house_type,
                        city_slug=city_slug,
                    )
                    continue
                if house_type is None:
                    for htype in _HOUSE_TYPES:
                        queue.append(
                            (action, min_p, max_p, nb_slug, htype, city_slug)
                        )
                    logger.info(
                        "quintoandar_fanout_house_types",
                        action=action,
                        min_p=min_p,
                        max_p=max_p,
                        neighborhood=nb_slug,
                        types=list(_HOUSE_TYPES),
                        city_slug=city_slug,
                    )
                    continue
                self.ssr_truncated_windows += 1
                self.ssr_truncated_houses_yielded += len(valid_houses)
                logger.warning(
                    "quintoandar_window_truncated",
                    action=action,
                    min_p=min_p,
                    max_p=max_p,
                    neighborhood=nb_slug,
                    house_type=house_type,
                    city_slug=city_slug,
                    houses_found=len(valid_houses),
                    ssr_page_ceiling=_SSR_PAGE_CEILING,
                )
            for house_data in unique_by(
                list(valid_houses.values()), listing_id_from_raw, seen=seen_ids
            ):
                house_data["price_query_min"] = min_p
                house_data["price_query_max"] = max_p
                house_data["_qa_city_slug"] = city_slug
                yield house_data
        logger.info(
            "quintoandar_ssr_ceiling_summary",
            truncated_windows=self.ssr_truncated_windows,
            truncated_houses_yielded=self.ssr_truncated_houses_yielded,
            ssr_page_ceiling=_SSR_PAGE_CEILING,
        )

    def _window_url(
        self,
        action: str,
        min_p: int,
        max_p: int,
        nb_slug: str | None,
        house_type: str | None = None,
        city_slug: str | None = None,
    ) -> str:
        active = city_slug or self.city_slug
        slug = f"{nb_slug}-{active}" if nb_slug else active
        type_seg = f"/{house_type}" if house_type else ""
        return (
            f"https://www.quintoandar.com.br/{action}/imovel/"
            f"{slug}{type_seg}/de-{min_p}-a-{max_p}-reais"
        )

    def _initial_price_windows(self, checkpoint: Any) -> list[_QaWindow]:
        scrape_type = (
            checkpoint.get("scrape_type", "both")
            if isinstance(checkpoint, dict)
            else "both"
        )
        bands = {"alugar": self._price_rent, "comprar": self._price_sale}
        rent_actions = ["alugar"] if scrape_type in ("rent", "both") else []
        sale_actions = ["comprar"] if scrape_type in ("sale", "both") else []
        actions = rent_actions + sale_actions
        windows: list[_QaWindow] = []
        for city in self._cities:
            city_slug = city["city_slug"]
            for action in actions:
                min_p, max_p = bands[action]
                windows.append((action, min_p, max_p, None, None, city_slug))
        return windows

    def _fetch_window_houses(self, url: str, action: str, min_p: int, max_p: int) -> dict:
        logger.info(
            "quintoandar_fetching_price_window", action=action, min_p=min_p, max_p=max_p
        )
        response = self._throttled_request("GET", url)
        if response.status_code != 200:
            logger.error(
                "quintoandar_http_error",
                status_code=response.status_code,
                text=response.text[:200],
            )
            return {}
        script = BeautifulSoup(response.text, "html.parser").find(
            "script", id="__NEXT_DATA__"
        )
        if not script or not script.string:
            logger.warning("quintoandar_no_next_data", url=url)
            return {}
        try:
            houses = json.loads(script.string)["props"]["pageProps"]["initialState"].get(
                "houses", {}
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("quintoandar_parse_error")
            return {}
        valid_houses = {
            key: value for key, value in houses.items() if isinstance(value, dict)
        }
        if not valid_houses:
            logger.debug("quintoandar_no_houses_in_window", min_p=min_p, max_p=max_p)
        return valid_houses

    @staticmethod
    def _enqueue_price_split(
        queue: collections.deque,
        action: str,
        min_p: int,
        max_p: int,
        nb_slug: str | None,
        house_type: str | None = None,
        city_slug: str = _DEFAULT_CITY_SLUG,
    ) -> bool:
        halves = bisect_price(min_p, max_p)
        if halves is None:
            return False
        (lo_a, hi_a), (lo_b, hi_b) = halves
        queue.extend(
            (
                (action, lo_a, hi_a, nb_slug, house_type, city_slug),
                (action, lo_b, hi_b, nb_slug, house_type, city_slug),
            )
        )
        logger.info(
            "quintoandar_splitting_window",
            min_p=min_p,
            max_p=max_p,
            mid=hi_a,
            neighborhood=nb_slug,
            house_type=house_type,
            city_slug=city_slug,
        )
        return True

    # Back-compat for unit tests that call _split_window directly.
    @staticmethod
    def _split_window(queue, action: str, min_p: int, max_p: int, houses: dict) -> bool:
        if len(houses) < _SSR_PAGE_CEILING:
            return False
        return QuintoAndarScraper._enqueue_price_split(
            queue, action, min_p, max_p, None, None, _DEFAULT_CITY_SLUG
        )

    def fetch_description(self, url: str) -> str:
        """GET a detail page and extract seller remarks / generated description."""
        if not (url or "").strip():
            return ""
        try:
            response = self._throttled_request("GET", url, follow_redirects=True)
        except CircuitBreakerOpenError:
            logger.warning("quintoandar_description_circuit_open", url=url)
            return ""
        except Exception as exc:  # noqa: BLE001 — detail enrich must not abort scrape
            logger.warning(
                "quintoandar_description_fetch_error", url=url, error=str(exc)
            )
            return ""
        if response.status_code != 200:
            logger.info(
                "quintoandar_description_http",
                url=url,
                status_code=response.status_code,
            )
            return ""
        text = extract_quintoandar_description(response.text or "")
        if not text:
            logger.info("quintoandar_description_empty", url=url)
        return text

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert QuintoAndar JSON into our internal PropertyCandidate format."""
        neighbourhood = raw.get("neighbourhood")
        address_str = self._format_address(raw.get("address", {}), neighbourhood)
        image_urls = self._image_urls(raw.get("photos", []))
        rent_price, sale_price, condo_fee, iptu, fees_bundled, fees_note, partial = (
            self._prices_and_fees(raw)
        )
        is_rent = rent_price > 0
        is_sale = sale_price > 0
        price = rent_price if is_rent else sale_price
        if price <= 0:
            raise ValueError(f"Invalid price: {price}")
        location_dict = self._location(raw.get("location", {}))
        listings = self._listings(
            raw, rent_price, sale_price, condo_fee, iptu, fees_bundled, fees_note, partial
        )
        amenities = (raw.get("amenities") or []) + (raw.get("installations") or [])
        address_obj = raw.get("address") or {}
        city = address_obj.get("city") if isinstance(address_obj, dict) else None
        state = (
            (address_obj.get("state") or address_obj.get("uf") or address_obj.get("region"))
            if isinstance(address_obj, dict)
            else None
        )
        slug_for_fallback = (
            raw.get("_qa_city_slug") or self.city_slug or _DEFAULT_CITY_SLUG
        )
        fallback_city, fallback_state = _city_state_from_slug(str(slug_for_fallback))
        if not state:
            state = fallback_state
        if not city:
            city = fallback_city

        # Build property candidate
        return {
            "platform": "quintoandar",
            "platform_id": str(raw.get("id", "")),
            "title": raw.get("type", "Property") + f" in {neighbourhood or city}",
            "description": (
                (raw.get("description") or raw.get("remarks") or "").strip()
            ),
            "price": price,
            "area_m2": float(raw.get("area") or 0.0),
            "bedrooms": int(raw.get("bedrooms") or 0),
            "bathrooms": int(raw.get("bathrooms") or 0),
            "parking": int(raw.get("parkingSpots") or raw.get("parkingSpaces") or 0),
            "location": location_dict,
            "address": address_str,
            "image_urls": image_urls,
            "props_json": {
                "type": _normalize_qa_property_type(raw.get("type")),
                "condo_fee": condo_fee,
                "iptu": iptu,
                "fees_bundled": fees_bundled or None,
                "isFurnished": raw.get("isFurnished"),
                "neighborhood": neighbourhood,
                "city": city,
                "state": state,
                "amenities": amenities,
                "available_for_rent": is_rent,
                "available_for_sale": is_sale,
            },
            "listings": listings,
        }

    @staticmethod
    def _format_address(address: dict, neighbourhood: str | None) -> str:
        parts = [address.get("address"), neighbourhood, address.get("city")]
        return ", ".join(part for part in parts if part) or "Address unavailable"

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
                urls.append(
                    value
                    if value.startswith("http")
                    else f"https://www.quintoandar.com.br/img/{value}"
                )
        return urls

    def _prices_and_fees(self, raw: dict) -> tuple:
        partial, sale = float(raw.get("rentPrice") or 0), float(raw.get("salePrice") or 0)
        condo, iptu, bundled, note = self._extract_fees(raw)
        total_cost = raw.get("totalCost")
        rent = (
            float(total_cost)
            if total_cost not in (None, "", 0, 0.0)
            else partial + (condo or 0) + (iptu or 0)
        )
        if condo is None and iptu is None and partial > 0 and rent > partial:
            condo, bundled, note = (
                round(rent - partial, 2),
                True,
                "condo+IPTU derived from totalCost - rentPrice",
            )
        return rent, sale, condo, iptu, bundled, note, partial

    @staticmethod
    def _location(location: dict) -> dict | None:
        lat, lon = location.get("lat"), location.get("lon", location.get("lng"))
        return (
            {"lat": float(lat), "lon": float(lon)}
            if lat is not None and lon is not None
            else None
        )

    @staticmethod
    def _listings(raw, rent, sale, condo, iptu, bundled, note, partial) -> list[dict]:
        amenities = (raw.get("amenities") or []) + (raw.get("installations") or [])
        accepts_pets = (
            "PODE_TER_ANIMAIS_DE_ESTIMACAO" in amenities
            or raw.get("acceptsPets") is True
            or raw.get("petsAllowed") is True
        )
        base = {
            "platform": "quintoandar",
            "platform_listing_id": str(raw.get("id", "")),
            "currency": "BRL",
            "url": f"https://www.quintoandar.com.br/imovel/{raw.get('id', '')}",
            "is_furnished": raw.get("isFurnished"),
            "accepts_pets": accepts_pets if accepts_pets else None,
            "condo_fee": condo,
            "iptu": iptu,
        }

        def listing(kind, price, partial_price):
            details = {"partial_price": partial_price}
            if bundled:
                details["fees_bundled"] = True
            if note:
                details["fees_note"] = note
            base_price = float(partial_price) if kind == "rent" and partial_price else None
            return {
                **base,
                "listing_type": kind,
                "price": price,
                "base_price": base_price,
                "raw_json": details,
            }

        return [
            listing(kind, price, source_price)
            for kind, price, source_price in (
                ("rent", rent, partial),
                ("sale", sale, sale),
            )
            if price > 0
        ]

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
