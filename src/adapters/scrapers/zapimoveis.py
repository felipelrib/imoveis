"""ZapImóveis scraper (BIN-127 / FR-23).

Parses Next.js Flight (``__next_f.push``) ``listings`` arrays embedded in
search HTML. JSON-LD ``ItemList`` / ``Product`` is a fallback when Flight
is absent. Cloudflare 403s are environmental (proxy), not parse failures.
"""

from __future__ import annotations

import collections
import json
import random
import re
import time
from typing import Any, Dict, Iterator
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.flight_html import (
    extract_json_array_after,
    extract_json_object_after,
    iter_flight_chunks,
)
from adapters.scrapers.funnel import bisect_price, listing_id_from_raw, unique_by
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from adapters.scrapers.registry import ScraperRegistry
from core.exceptions import CircuitBreakerOpenError
from infra.logging import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://www.zapimoveis.com.br"
_UNIT_TYPES = ("apartamentos", "casas")
_DEFAULT_CITY = "mg+belo-horizonte"
_LISTING_ID_RE = re.compile(r"(?:id-|/imovel/)(?:[^\s\"']*?-)?(\d{6,})", re.I)
_HTML_PARSER = "html.parser"
_SCHEMA_TYPE = "@type"

# (business_path, unit_type, min_p, max_p, city_slug, neighborhood|None)
_ZapWindow = tuple[str, str, int, int, str, str | None]


def _description_from_jsonld(html: str) -> str:
    soup = BeautifulSoup(html or "", _HTML_PARSER)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get(_SCHEMA_TYPE) == "Product":
            text = (data.get("description") or "").strip()
            if text:
                return text
    return ""


def extract_zapimoveis_description(html: str) -> str:
    """Pull listing description from detail Flight or Product JSON-LD."""
    listing = _extract_detail_listing(html or "")
    if isinstance(listing, dict):
        text = (listing.get("description") or "").strip()
        if text:
            return text
    return _description_from_jsonld(html or "")


def _extract_flight_listings(html: str) -> list[dict]:
    """Parse ``\"listings\":[...]`` arrays from Next.js Flight push payloads."""
    for chunk in iter_flight_chunks(html or ""):
        if "listings" not in chunk or ("coordinates" not in chunk and "prices" not in chunk):
            continue
        parsed = extract_json_array_after(chunk, '"listings":')
        if not parsed:
            continue
        out = [item for item in parsed if isinstance(item, dict) and item.get("id")]
        if out:
            return out
    return []


def _extract_detail_listing(html: str) -> dict | None:
    """Parse a single ``\"listing\":{...}`` object from detail Flight HTML."""
    for chunk in iter_flight_chunks(html or ""):
        if "listing" not in chunk or "prices" not in chunk:
            continue
        for marker in ('"listing":', '"listing" :'):
            obj = extract_json_object_after(chunk, marker)
            if isinstance(obj, dict) and obj.get("id"):
                return obj
    return None


def _extract_jsonld_products(html: str) -> list[dict]:
    """Fallback: Product cards from schema.org ItemList."""
    soup = BeautifulSoup(html or "", _HTML_PARSER)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get(_SCHEMA_TYPE) != "ItemList":
            continue
        out = _products_from_item_list(data)
        if out:
            return out
    return []


def _products_from_item_list(data: dict) -> list[dict]:
    out: list[dict] = []
    for entry in data.get("itemListElement") or []:
        if not isinstance(entry, dict):
            continue
        item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
        if isinstance(item, dict) and (item.get("@id") or item.get("url")):
            out.append(item)
    return out


def _listing_id_from_url(url: str) -> str | None:
    if not url:
        return None
    match = _LISTING_ID_RE.search(url)
    return match.group(1) if match else None


def _city_state_from_slug(city_slug: str) -> tuple[str, str]:
    slug = (city_slug or "").casefold()
    if "campinas" in slug:
        return "Campinas", "SP"
    if "sao-paulo" in slug or "são-paulo" in slug:
        return "São Paulo", "SP"
    return "Belo Horizonte", "MG"


def _first_int(values: Any) -> int | None:
    if isinstance(values, list) and values:
        try:
            return int(values[0])
        except (TypeError, ValueError):
            return None
    if isinstance(values, (int, float)):
        return int(values)
    return None


def _positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _resolve_image_url(src: str) -> str:
    if not src:
        return ""
    return (
        src.replace("{description}", "foto")
        .replace("{action}", "fit-in")
        .replace("{width}", "614")
        .replace("{height}", "297")
    )


@ScraperRegistry.register("zapimoveis")
class ZapImoveisScraper(BaseScraper):
    """Scrapes ZapImóveis search pages via Flight listings + price funnel."""

    def __init__(self, platform_name: str, config: Dict[str, Any]):
        super().__init__(platform_name, config)
        self._rate_limit = config.get("rate_limit", 20)
        self._jitter_min = config.get("jitter_min", 2)
        self._jitter_max = config.get("jitter_max", 6)
        extra = config.get("extra") or {}
        self._max_pages = int(extra.get("max_pages", 5))
        self._price_rent = self._parse_price_pair(extra.get("price_rent"), (500, 15000))
        self._price_sale = self._parse_price_pair(extra.get("price_sale"), (100000, 5000000))
        self._cities = self._parse_cities(extra)
        self._city_neighborhoods = {
            c["city_slug"]: c["neighborhoods"] for c in self._cities
        }
        self._neighborhoods = list(self._city_neighborhoods[self._cities[0]["city_slug"]])

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
        slug = str(extra.get("city_slug") or _DEFAULT_CITY)
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

    def start(self) -> None:
        self.session = self.create_http_session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
            }
        )
        self._cb = RedisCircuitBreaker(
            platform="zapimoveis", failure_threshold=5, cooldown_seconds=120
        )

    def close(self) -> None:
        if hasattr(self, "session") and self.session is not None:
            self.session.close()

    def _throttled_request(self, url: str) -> Any:
        if self._cb.is_open():
            raise CircuitBreakerOpenError(
                f"ZapImóveis circuit breaker is open — skipping {url}"
            )
        delay = random.uniform(
            self._jitter_min, max(self._jitter_min + 0.1, self._jitter_max)
        )
        time.sleep(delay)
        response = self.session.get(url, follow_redirects=True)
        if 200 <= response.status_code < 300:
            self._cb.record_success()
        elif response.status_code >= 500 or response.status_code == 429:
            self._cb.record_failure()
        return response

    def fetch_description(self, url: str) -> str:
        if not (url or "").strip():
            return ""
        try:
            response = self._throttled_request(url)
        except CircuitBreakerOpenError:
            logger.warning("zapimoveis_description_circuit_open", url=url)
            return ""
        except Exception as exc:  # detail enrich must not abort scrape
            logger.warning("zapimoveis_description_fetch_error", url=url, error=str(exc))
            return ""
        if response.status_code != 200:
            logger.info(
                "zapimoveis_description_http",
                url=url,
                status_code=response.status_code,
            )
            return ""
        text = extract_zapimoveis_description(response.text or "")
        if not text:
            logger.info("zapimoveis_description_empty", url=url)
        return text

    def fetch_pages(self, checkpoint: Any = None) -> Iterator[Dict[str, Any]]:
        if not isinstance(checkpoint, dict):
            checkpoint = {}

        queue: collections.deque[_ZapWindow] = collections.deque(
            self._initial_windows(checkpoint)
        )
        visited: set[_ZapWindow] = set()
        kept_by_id: dict[str, dict] = {}

        while queue:
            window = queue.popleft()
            if window in visited:
                continue
            visited.add(window)
            collected, saturated = self._fetch_window(*window)
            if not collected and not saturated:
                continue
            if saturated and self._fan_out_saturated_window(window, collected, queue):
                continue
            yield from self._yield_merged_listings(collected, kept_by_id)

    def _fan_out_saturated_window(
        self,
        window: _ZapWindow,
        collected: list[dict],
        queue: "collections.deque[_ZapWindow]",
    ) -> bool:
        """Split/fan-out a saturated window. Returns True when re-enqueued.

        When re-enqueued, the caller must NOT yield ``collected`` — the finer
        windows will re-fetch that inventory. Otherwise the caller yields the
        already-collected listings as a best effort.
        """
        business, unit_type, min_p, max_p, city_slug, neighborhood = window
        listing_type = "rent" if business == "aluguel" else "sale"

        if collected and not self._price_filter_effective(
            collected, min_p, max_p, listing_type
        ):
            logger.warning(
                "zapimoveis_price_filter_ineffective",
                business=business,
                unit_type=unit_type,
                city_slug=city_slug,
                min_p=min_p,
                max_p=max_p,
                collected=len(collected),
            )
            return False

        halves = bisect_price(min_p, max_p)
        if halves:
            (lo_a, hi_a), (lo_b, hi_b) = halves
            queue.append((business, unit_type, lo_a, hi_a, city_slug, neighborhood))
            queue.append((business, unit_type, lo_b, hi_b, city_slug, neighborhood))
            return True

        if neighborhood is None:
            neighborhoods = self._city_neighborhoods.get(city_slug) or []
            if neighborhoods:
                for nb in neighborhoods:
                    queue.append((business, unit_type, min_p, max_p, city_slug, nb))
                return True

        logger.warning(
            "zapimoveis_window_truncated",
            business=business,
            unit_type=unit_type,
            city_slug=city_slug,
            min_p=min_p,
            max_p=max_p,
            neighborhood=neighborhood,
            collected=len(collected),
        )
        return False

    def _initial_windows(self, checkpoint: dict) -> list[_ZapWindow]:
        scrape_type = (checkpoint.get("scrape_type") or "all").lower()
        businesses: list[str] = []
        if scrape_type in ("all", "rent", "aluguel"):
            businesses.append("aluguel")
        if scrape_type in ("all", "sale", "venda"):
            businesses.append("venda")
        if not businesses:
            businesses = ["aluguel", "venda"]

        windows: list[_ZapWindow] = []
        for city in self._cities:
            city_slug = city["city_slug"]
            for business in businesses:
                min_p, max_p = (
                    self._price_rent if business == "aluguel" else self._price_sale
                )
                for unit_type in _UNIT_TYPES:
                    windows.append(
                        (business, unit_type, min_p, max_p, city_slug, None)
                    )
        return windows

    def _build_search_url(
        self,
        business: str,
        unit_type: str,
        city_slug: str,
        min_p: int,
        max_p: int,
        page: int,
        neighborhood: str | None,
    ) -> str:
        location = city_slug
        if neighborhood:
            location = f"{city_slug}/{neighborhood}"
        path = f"{_BASE_URL}/{business}/{unit_type}/{location}/"
        query = {
            "precoMinimo": min_p,
            "precoMaximo": max_p,
            "pagina": page,
        }
        return f"{path}?{urlencode(query)}"

    def _fetch_search_page(self, url: str) -> list[dict]:
        """GET one search page and parse listings; ``[]`` stops pagination."""
        try:
            response = self._throttled_request(url)
        except CircuitBreakerOpenError:
            logger.warning("zapimoveis_circuit_open", url=url)
            return []
        except Exception as exc:
            logger.warning("zapimoveis_fetch_error", url=url, error=str(exc))
            return []
        if response.status_code == 403:
            logger.warning("zapimoveis_cloudflare_403", url=url)
            return []
        if response.status_code != 200:
            logger.info(
                "zapimoveis_http", url=url, status_code=response.status_code
            )
            return []
        return self.extract_listings(response.text or "")

    def _fetch_window(
        self,
        business: str,
        unit_type: str,
        min_p: int,
        max_p: int,
        city_slug: str,
        neighborhood: str | None,
    ) -> tuple[list[dict], bool]:
        collected: list[dict] = []
        saturated = False
        listing_type = "rent" if business == "aluguel" else "sale"
        for page in range(1, self._max_pages + 1):
            url = self._build_search_url(
                business, unit_type, city_slug, min_p, max_p, page, neighborhood
            )
            page_listings = self._fetch_search_page(url)
            if not page_listings:
                break
            for raw in page_listings:
                stamped = dict(raw)
                stamped["_zap_listing_type"] = listing_type
                stamped["_zap_city_slug"] = city_slug
                collected.append(stamped)
            if len(page_listings) < 10:
                break
            if page >= self._max_pages:
                saturated = True
        return collected, saturated

    @staticmethod
    def _listing_side_price(raw: dict, listing_type: str) -> float | None:
        prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
        side_key = "rental" if listing_type == "rent" else "sale"
        side = prices.get(side_key) if isinstance(prices.get(side_key), dict) else None
        return _positive_float((side or {}).get("value"))

    @classmethod
    def _price_filter_effective(
        cls,
        collected: list[dict],
        min_p: int,
        max_p: int,
        listing_type: str,
    ) -> bool:
        """Return True when enough listing prices sit inside the requested band.

        Zap sometimes ignores ``precoMinimo``/``precoMaximo`` (Cloudflare / A-B).
        Bisecting then explodes into thousands of identical windows — refuse to
        split when the band clearly is not applied.
        """
        in_band = 0
        priced = 0
        for raw in collected:
            price = cls._listing_side_price(raw, listing_type)
            if price is None:
                continue
            priced += 1
            if min_p <= price <= max_p:
                in_band += 1
        if priced == 0:
            return False
        return (in_band / priced) >= 0.5

    def extract_listings(self, html: str) -> list[dict]:
        """Public parse entry used by cassette tests."""
        flight = _extract_flight_listings(html)
        if flight:
            return flight
        return [
            self._product_to_raw(product) for product in _extract_jsonld_products(html)
        ]

    @staticmethod
    def _product_listing_type(offers: dict) -> str:
        action = offers.get("potentialAction") or {}
        return "sale" if str(action.get(_SCHEMA_TYPE, "")).lower().startswith("buy") else "rent"

    @staticmethod
    def _product_condo_fee(offers: dict) -> float | None:
        add = offers.get("additionalProperty")
        if isinstance(add, dict) and "condo" in str(add.get("name", "")).lower():
            return _positive_float(add.get("value"))
        return None

    @classmethod
    def _product_prices(cls, offers: dict) -> tuple[str, dict[str, Any]]:
        listing_type = cls._product_listing_type(offers)
        prices: dict[str, Any] = {"rental": None, "sale": None}
        price_val = _positive_float(offers.get("price"))
        if price_val is not None:
            side = {
                "value": price_val,
                "condominium": cls._product_condo_fee(offers),
                "iptu": None,
                "multiple": False,
            }
            prices["sale" if listing_type == "sale" else "rental"] = side
        return listing_type, prices

    @staticmethod
    def _product_amenities(product: dict) -> dict[str, list]:
        floor_size = product.get("floorSize")
        area = floor_size.get("value") if isinstance(floor_size, dict) else None
        bedrooms = product.get("numberOfBedrooms")
        bathrooms = product.get("numberOfBathroomsTotal")
        return {
            "usableAreas": [area] if area is not None else [],
            "bedrooms": [bedrooms] if bedrooms is not None else [],
            "bathrooms": [bathrooms] if bathrooms is not None else [],
            "parkingSpaces": [],
            "values": [],
        }

    @classmethod
    def _product_to_raw(cls, product: dict) -> dict:
        """Map schema.org Product → Flight-like raw dict for normalize()."""
        offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
        listing_type, prices = cls._product_prices(offers)
        lid = str(
            product.get("@id") or _listing_id_from_url(str(product.get("url") or "")) or ""
        )
        address = product.get("address") if isinstance(product.get("address"), dict) else {}
        images = product.get("image") or []
        if isinstance(images, str):
            images = [images]
        return {
            "id": lid,
            "title": product.get("name") or "",
            "href": product.get("url") or "",
            "business": "SALE" if listing_type == "sale" else "RENTAL",
            "prices": prices,
            "address": {
                "city": address.get("addressLocality"),
                "stateAcronym": address.get("addressRegion"),
                "street": address.get("streetAddress"),
                "neighborhood": None,
                "coordinates": {},
            },
            "amenities": cls._product_amenities(product),
            "medias": {
                "images": [{"dangerousSrc": u} for u in images if isinstance(u, str)]
            },
            "description": product.get("description") or "",
            "unitType": "APARTMENT",
            "_zap_listing_type": listing_type,
        }

    def _yield_merged_listings(
        self,
        collected: list[dict],
        kept_by_id: dict[str, dict],
    ) -> Iterator[Dict[str, Any]]:
        for listing in unique_by(collected, listing_id_from_raw):
            lid = listing_id_from_raw(listing)
            if lid is None:
                yield listing
                continue
            kept = kept_by_id.get(lid)
            if kept is None:
                kept_by_id[lid] = listing
                yield listing
                continue
            if self._merge_dual_window_prices(kept, listing):
                yield kept

    @staticmethod
    def _merge_dual_window_prices(kept: dict, incoming: dict) -> bool:
        kept_type = kept.get("_zap_listing_type")
        incoming_type = incoming.get("_zap_listing_type")
        if kept_type not in ("rent", "sale") or incoming_type not in ("rent", "sale"):
            return False
        if kept_type == incoming_type:
            return False
        prices = dict(kept.get("prices") or {})
        incoming_prices = incoming.get("prices") or {}
        if kept_type == "rent" and incoming_prices.get("sale"):
            prices["sale"] = incoming_prices["sale"]
        elif kept_type == "sale" and incoming_prices.get("rental"):
            prices["rental"] = incoming_prices["rental"]
        else:
            return False
        if not prices.get("rental") or not prices.get("sale"):
            return False
        kept["prices"] = prices
        kept.pop("_zap_listing_type", None)
        return True

    @staticmethod
    def _price_sides(raw: dict) -> tuple[dict, dict]:
        prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
        rental = prices.get("rental") if isinstance(prices.get("rental"), dict) else {}
        sale = prices.get("sale") if isinstance(prices.get("sale"), dict) else {}
        return rental or {}, sale or {}

    @classmethod
    def _normalize_prices(cls, raw: dict, platform_id: str) -> dict[str, Any]:
        rental, sale = cls._price_sides(raw)
        rent_price = _positive_float(rental.get("value")) or 0.0
        sale_price = _positive_float(sale.get("value")) or 0.0
        if rent_price <= 0 and sale_price <= 0:
            raise ValueError(f"Invalid Zap price for {platform_id}")
        fee_src = rental or sale
        return {
            "rent_price": rent_price,
            "sale_price": sale_price,
            "condo_fee": _positive_float(fee_src.get("condominium")),
            "iptu": _positive_float(fee_src.get("iptu")),
        }

    @staticmethod
    def _normalize_amenities(raw: dict) -> dict[str, Any]:
        amenities = raw.get("amenities") if isinstance(raw.get("amenities"), dict) else {}
        amenity_values = [
            str(v) for v in (amenities.get("values") or []) if v is not None
        ]
        accepts_pets = (
            "PETS_ALLOWED" in amenity_values or raw.get("petsAllowed") is True
        )
        return {
            "area": _first_int(amenities.get("usableAreas")),
            "bedrooms": _first_int(amenities.get("bedrooms")),
            "bathrooms": _first_int(amenities.get("bathrooms")),
            "parking": _first_int(amenities.get("parkingSpaces")),
            "amenity_values": amenity_values,
            "accepts_pets": bool(accepts_pets) if accepts_pets else None,
        }

    @staticmethod
    def _normalize_location(address: dict) -> dict | None:
        coords = (
            address.get("coordinates")
            if isinstance(address.get("coordinates"), dict)
            else {}
        )
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        if lat is not None and lon is not None:
            return {"lat": float(lat), "lon": float(lon)}
        return None

    @staticmethod
    def _normalize_state(state: Any) -> Any:
        if state and len(str(state)) > 2:
            lowered = str(state).casefold()
            if lowered.startswith("minas"):
                return "MG"
            if "paulo" in lowered:
                return "SP"
        return state

    @classmethod
    def _normalize_address(cls, raw: dict) -> dict[str, Any]:
        address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
        neighborhood = address.get("neighborhood")
        fallback_city, fallback_state = _city_state_from_slug(
            str(raw.get("_zap_city_slug") or _DEFAULT_CITY)
        )
        city = address.get("city") or fallback_city
        state = cls._normalize_state(
            address.get("stateAcronym") or address.get("state") or fallback_state
        )
        street_parts = [
            address.get("street"),
            address.get("streetNumber"),
            neighborhood,
            city,
        ]
        address_str = (
            ", ".join(str(p) for p in street_parts if p) or "Address unavailable"
        )
        return {
            "city": city,
            "state": state,
            "neighborhood": neighborhood,
            "address_str": address_str,
            "location": cls._normalize_location(address),
        }

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Zap Flight/JSON-LD listing into PropertyCandidate fields."""
        platform_id = str(raw.get("id") or "")
        if not platform_id:
            raise ValueError("ZapImóveis listing missing id")

        price_info = self._normalize_prices(raw, platform_id)
        rent_price = price_info["rent_price"]
        sale_price = price_info["sale_price"]
        condo_fee = price_info["condo_fee"]
        iptu = price_info["iptu"]

        amenity_info = self._normalize_amenities(raw)
        address_info = self._normalize_address(raw)
        neighborhood = address_info["neighborhood"]
        city = address_info["city"]

        image_urls = self._image_urls(raw)
        href = (raw.get("href") or "").strip()
        if not href and platform_id:
            href = f"{_BASE_URL}/imovel/id-{platform_id}/"

        price = rent_price if rent_price > 0 else sale_price
        listings = self._listings(
            platform_id=platform_id,
            href=href,
            rent_price=rent_price,
            sale_price=sale_price,
            condo_fee=condo_fee,
            iptu=iptu,
            accepts_pets=amenity_info["accepts_pets"],
        )

        from core.property_type import normalize_property_type

        unit_type = raw.get("unitType") or ""
        area = amenity_info["area"]
        return {
            "platform": "zapimoveis",
            "platform_id": platform_id,
            "title": (raw.get("title") or f"Property in {neighborhood or city}").strip(),
            "description": (raw.get("description") or "").strip(),
            "price": float(price),
            "area_m2": float(area) if area is not None else None,
            "bedrooms": amenity_info["bedrooms"],
            "bathrooms": amenity_info["bathrooms"],
            "parking": amenity_info["parking"],
            "location": address_info["location"],
            "address": address_info["address_str"],
            "image_urls": image_urls,
            "props_json": {
                "type": normalize_property_type(str(unit_type) if unit_type else None),
                "condo_fee": condo_fee,
                "iptu": iptu,
                "fees_bundled": False,
                "neighborhood": neighborhood,
                "city": city,
                "state": address_info["state"],
                "amenities": amenity_info["amenity_values"],
                "available_for_rent": rent_price > 0,
                "available_for_sale": sale_price > 0,
                "publication_type": raw.get("publicationType"),
            },
            "listings": listings,
        }

    @staticmethod
    def _image_urls(raw: dict) -> list[str]:
        medias = raw.get("medias") if isinstance(raw.get("medias"), dict) else {}
        images = medias.get("images") or []
        urls: list[str] = []
        for photo in images:
            if isinstance(photo, str):
                value = photo
            elif isinstance(photo, dict):
                value = photo.get("dangerousSrc") or photo.get("url") or photo.get("src")
            else:
                value = None
            if value:
                resolved = _resolve_image_url(str(value))
                if resolved.startswith("http"):
                    urls.append(resolved)
        return urls

    @staticmethod
    def _listings(
        *,
        platform_id: str,
        href: str,
        rent_price: float,
        sale_price: float,
        condo_fee: float | None,
        iptu: float | None,
        accepts_pets: bool | None,
    ) -> list[dict]:
        base = {
            "platform": "zapimoveis",
            "platform_listing_id": platform_id,
            "currency": "BRL",
            "url": href,
            "accepts_pets": accepts_pets,
            "condo_fee": condo_fee,
            "iptu": iptu,
        }
        out: list[dict] = []
        if rent_price > 0:
            out.append(
                {
                    **base,
                    "listing_type": "rent",
                    "price": float(rent_price),
                    "base_price": float(rent_price),
                    "raw_json": {"fees_bundled": False},
                }
            )
        if sale_price > 0:
            out.append(
                {
                    **base,
                    "listing_type": "sale",
                    "price": float(sale_price),
                    "base_price": float(sale_price),
                    "raw_json": {"fees_bundled": False},
                }
            )
        return out
