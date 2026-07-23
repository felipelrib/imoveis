"""
OLX Brazil scraper implementation.

Scrapes real-estate listings from olx.com.br by parsing the embedded
``__NEXT_DATA__`` JSON state, following the same pattern as QuintoAndar.
OLX Brazil serves Next.js pages with structured listing data in the
page's initial state.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Dict, Iterator

from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from adapters.scrapers.registry import ScraperRegistry
from core.exceptions import CircuitBreakerOpenError
from infra.logging import get_logger

logger = get_logger(__name__)

_NON_DIGIT_RE = re.compile(r"[^\d]")


@ScraperRegistry.register("olx")
class OLXScraper(BaseScraper):
    """Scrapes properties from OLX Brazil using page iteration."""

    _BASE_URL = "https://www.olx.com.br/imoveis"

    def __init__(self, platform_name: str, config: Dict[str, Any]):
        super().__init__(platform_name, config)
        self._rate_limit = config.get("rate_limit", 20)
        self._jitter_min = config.get("jitter_min", 2)
        self._jitter_max = config.get("jitter_max", 6)
        extra = config.get("extra") or {}
        self._max_pages = extra.get("max_pages", 5)
        region = extra.get("region", "mg")
        city_slug = extra.get("city_slug", "belo-horizonte")
        self._RENT_PATHS = [
            f"aluguel/apartamentos/{region}/{city_slug}",
            f"aluguel/apartamentos/{region}/{city_slug}-e-regiao",
            f"aluguel/casas/{region}/{city_slug}",
        ]
        self._SALE_PATHS = [
            f"venda/apartamentos/{region}/{city_slug}",
            f"venda/apartamentos/{region}/{city_slug}-e-regiao",
            f"venda/casas/{region}/{city_slug}",
        ]

    def start(self) -> None:
        self.session = self.create_http_session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control": "no-cache",
            }
        )
        self._cb = RedisCircuitBreaker(platform="olx", failure_threshold=5, cooldown_seconds=120)

    def close(self) -> None:
        if hasattr(self, "session") and self.session is not None:
            self.session.close()

    def _throttled_request(self, url: str) -> Any:
        """Sleep for a random jitter then make the request."""
        if self._cb.is_open():
            raise CircuitBreakerOpenError(
                f"OLX circuit breaker is open — skipping {url}"
            )

        delay = random.uniform(
            self._jitter_min, max(self._jitter_min + 0.1, self._jitter_max)
        )
        time.sleep(delay)
        response = self.session.get(url, follow_redirects=True)

        # Track success/failure for circuit breaker
        if 200 <= response.status_code < 300:
            self._cb.record_success()
        elif response.status_code >= 500 or response.status_code == 429:
            self._cb.record_failure()
        return response

    # ------------------------------------------------------------------
    # fetch_pages — iterator over raw listing dicts
    # ------------------------------------------------------------------

    def fetch_pages(self, checkpoint: Any = None) -> Iterator[Dict[str, Any]]:
        """Yield raw listing dicts from OLX search pages.

        Iterates over rent and sale paths, page by page, parsing the
        ``__NEXT_DATA__`` embedded JSON.  Stops when no listings are found
        or the configured page limit is reached.
        """
        if not isinstance(checkpoint, dict):
            checkpoint = {}

        scrape_type = checkpoint.get("scrape_type", "both")

        paths: list[str] = []
        if scrape_type in ("rent", "both"):
            paths.extend(self._RENT_PATHS)
        if scrape_type in ("sale", "both"):
            paths.extend(self._SALE_PATHS)

        for path in paths:
            for page in range(1, self._max_pages + 1):
                url = f"{self._BASE_URL}/{path}?o={page}"
                listings = self._fetch_page_listings(url, page)
                if not listings:
                    break
                for listing in listings:
                    listing["_olx_url"] = url
                    yield listing

    def _fetch_page_listings(self, url: str, page: int) -> list[dict]:
        logger.info("olx_fetching_page", url=url, page=page)
        try:
            response = self._throttled_request(url)
        except Exception:
            logger.exception("olx_request_error", url=url)
            return []
        if response.status_code != 200:
            logger.warning("olx_http_error", status_code=response.status_code, url=url)
            return []
        script = BeautifulSoup(response.text, "html.parser").find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.warning("olx_no_next_data", url=url)
            return []
        try:
            listings = self._extract_listings(json.loads(script.string))
        except (json.JSONDecodeError, TypeError):
            logger.exception("olx_json_parse_error", url=url)
            return []
        if listings:
            logger.info("olx_page_listings", url=url, page=page, count=len(listings))
        else:
            logger.debug("olx_no_listings_in_page", url=url, page=page)
        return listings

    def _extract_listings(self, data: dict) -> list[dict]:
        """Navigate the OLX page data tree to find listing objects."""
        # Strategy 1: Standard Next.js pageProps → initialState → ads
        try:
            page_props = data.get("props", {}).get("pageProps", {})
        except (AttributeError, TypeError):
            return []

        # Try common state shapes
        # Shape A: pageProps → initialState → search → ads
        state = page_props.get("initialState") or page_props.get("state") or {}

        # Navigate nested structures
        for key_path in [
            ("search", "ads"),
            ("ads",),
            ("searchResult", "ads"),
            ("listings",),
            ("data", "ads"),
            ("data",),
        ]:
            obj = state
            found = True
            for k in key_path:
                if isinstance(obj, dict):
                    obj = obj.get(k)
                elif isinstance(obj, list):
                    break
                else:
                    found = False
                    break
            if found and isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]

        # Strategy 2: pageProps directly has ads/data list
        for key in ("ads", "listings", "data"):
            val = page_props.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]

        return []

    # ------------------------------------------------------------------
    # normalize — convert raw OLX listing to PropertyCandidate format
    # ------------------------------------------------------------------

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an OLX listing dict into the internal PropertyCandidate format."""

        # --- Platform ID ---
        platform_id = str(
            raw.get("list_id")
            or raw.get("id")
            or raw.get("ad_id")
            or ""
        )
        if not platform_id:
            raise ValueError("OLX listing missing id/list_id")

        # --- Title ---
        title = raw.get("subject") or raw.get("title") or "Imóvel"

        # --- Description ---
        description = raw.get("body") or raw.get("description") or ""

        # --- Price ---
        price = self._parse_price(raw)

        # --- Location ---
        location_dict, address_str = self._parse_location(raw)

        # --- Images ---
        image_urls = self._parse_images(raw)

        # --- Property attributes ---
        props = self._parse_properties(raw)

        # --- Listing type ---
        listing_type = self._detect_listing_type(raw)

        # Calculate full rent price for rentals
        if listing_type == "rent":
            price = price + float(props.get("condo_fee") or 0.0) + float(props.get("iptu") or 0.0)

        # --- Build listings array ---
        listing_url = raw.get("url") or raw.get("_olx_url") or f"https://www.olx.com.br/detalhes/{platform_id}"
        listings = []
        listings.append(
            {
                "platform": "olx",
                "platform_listing_id": platform_id,
                "listing_type": listing_type,
                "price": price,
                "currency": "BRL",
                "url": listing_url,
                "is_furnished": props.get("is_furnished"),
                "accepts_pets": props.get("accepts_pets"),
                "condo_fee": props.get("condo_fee"),
                "iptu": props.get("iptu"),
            }
        )

        # --- Neighborhood name ---
        neighborhood = (
            location_dict.get("neighborhood")
            if isinstance(location_dict, dict)
            else None
        ) or self._neighborhood_from_raw(raw)

        return {
            "platform": "olx",
            "platform_id": platform_id,
            "title": title,
            "description": description,
            "price": price,
            "area_m2": props.get("area_m2"),
            "bedrooms": props.get("bedrooms"),
            "bathrooms": props.get("bathrooms"),
            "parking": props.get("parking"),
            "location": {"lat": location_dict["lat"], "lon": location_dict["lon"]}
            if isinstance(location_dict, dict) and location_dict.get("lat") and location_dict.get("lon")
            else None,
            "address": address_str,
            "image_urls": image_urls,
            "props_json": {
                "neighborhood": neighborhood,
                "available_for_rent": listing_type == "rent",
                "available_for_sale": listing_type == "sale",
                "isFurnished": props.get("is_furnished"),
                "amenities": [],
            },
            "listings": listings,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_price(raw: dict) -> float:
        """Extract numeric price from OLX listing."""
        direct = OLXScraper._positive_number(raw.get(key) for key in ("value", "price", "pricingInfos"))
        if direct is not None:
            return direct
        pricing_infos = raw.get("pricingInfos")
        if isinstance(pricing_infos, list) and pricing_infos and isinstance(pricing_infos[0], dict):
            nested = OLXScraper._positive_number(pricing_infos[0].get(key) for key in ("value", "price"))
            if nested is not None:
                return nested
        for key in ("price_str", "value_str", "subject"):
            parsed = OLXScraper._parse_brazilian_number(raw.get(key))
            if parsed is not None:
                return parsed
        raise ValueError(f"Could not parse price from OLX listing: {raw.get('list_id', raw.get('id', '?'))}")

    @staticmethod
    def _positive_number(values) -> float | None:
        for value in values:
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    @staticmethod
    def _parse_brazilian_number(value: Any) -> float | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = float(re.sub(r"[^\d,.]", "", value).replace(".", "").replace(",", "."))
            return parsed if parsed > 0 else None
        except ValueError:
            return None

    @staticmethod
    def _coords_from_raw(raw: dict) -> tuple[float | None, float | None]:
        loc = raw.get("location") or raw.get("region") or {}
        lat = lon = None
        if isinstance(loc, dict):
            lat = loc.get("lat") or loc.get("latitude")
            lon = loc.get("lon") or loc.get("lng") or loc.get("longitude")
        if lat is None or lon is None:
            coords = raw.get("coordinates") or {}
            if isinstance(coords, dict):
                lat = lat or coords.get("lat")
                lon = lon or coords.get("lon") or coords.get("lng")
        try:
            return (float(lat) if lat else None, float(lon) if lon else None)
        except (TypeError, ValueError):
            return None, None

    @staticmethod
    def _address_from_loc(loc: dict) -> str | None:
        parts = []
        for key in ("address", "street"):
            if loc.get(key):
                parts.append(loc[key])
                break
        neighborhood = loc.get("neighborhood") or loc.get("neighborhoodName")
        if neighborhood:
            parts.append(neighborhood)
        city = loc.get("city") or loc.get("cityName")
        if city:
            parts.append(city)
        return ", ".join(parts) if parts else None

    @staticmethod
    def _parse_location(raw: dict) -> tuple:
        """Return (location_dict, address_str)."""
        loc = raw.get("location") or raw.get("region") or {}
        lat, lon = OLXScraper._coords_from_raw(raw)
        location_dict = None
        if lat and lon and isinstance(loc, dict):
            neighborhood = loc.get("neighborhood") or loc.get("neighborhoodName") or ""
            location_dict = {"lat": lat, "lon": lon, "neighborhood": neighborhood}
        address_str = OLXScraper._address_from_loc(loc) if isinstance(loc, dict) else None
        return location_dict, address_str

    @staticmethod
    def _parse_images(raw: dict) -> list[str]:
        """Extract image URLs from OLX listing."""
        images = raw.get("images") or raw.get("photos") or []
        urls = []
        for img in images:
            if isinstance(img, str):
                urls.append(img)
            elif isinstance(img, dict):
                url = (
                    img.get("src")
                    or img.get("url")
                    or img.get("path")
                    or img.get("original")
                )
                if url:
                    urls.append(url)
        return urls

    @staticmethod
    def _prop_map_from_raw(raw: dict) -> dict:
        raw_props = raw.get("properties") or raw.get("attributes") or []
        if isinstance(raw_props, list):
            prop_map = {}
            for p in raw_props:
                if isinstance(p, dict):
                    label = (p.get("label") or p.get("name") or "").lower()
                    value = p.get("value") or p.get("text") or ""
                    if label:
                        prop_map[label] = value
            return prop_map
        if isinstance(raw_props, dict):
            return {k.lower(): v for k, v in raw_props.items()}
        return {}

    @staticmethod
    def _set_float_prop(props: dict, prop_map: dict, keys: tuple[str, ...], dest: str) -> None:
        for key in keys:
            val = prop_map.get(key)
            if not val:
                continue
            try:
                props[dest] = float(re.sub(r"[^\d.]", "", str(val)).replace(",", "."))
            except (ValueError, TypeError):
                pass
            break

    @staticmethod
    def _set_int_prop(props: dict, prop_map: dict, keys: tuple[str, ...], dest: str) -> None:
        for key in keys:
            val = prop_map.get(key)
            if not val:
                continue
            try:
                props[dest] = int(_NON_DIGIT_RE.sub("", str(val)))
            except (ValueError, TypeError):
                pass
            break

    @staticmethod
    def _set_bool_prop(props: dict, prop_map: dict, keys: tuple[str, ...], dest: str) -> None:
        for key in keys:
            val = prop_map.get(key)
            if val:
                props[dest] = "sim" in str(val).lower()
                break

    @staticmethod
    def _parse_properties(raw: dict) -> dict:
        """Extract property attributes from OLX listing."""
        props = {}
        prop_map = OLXScraper._prop_map_from_raw(raw)
        OLXScraper._set_float_prop(props, prop_map, ("área", "area", "area_total", "area_util"), "area_m2")
        OLXScraper._set_int_prop(props, prop_map, ("quartos", "dormitórios", "bedrooms"), "bedrooms")
        OLXScraper._set_int_prop(props, prop_map, ("banheiros", "bathrooms"), "bathrooms")
        OLXScraper._set_int_prop(props, prop_map, ("vagas", "garagem", "parking", "parking_spaces"), "parking")
        OLXScraper._set_float_prop(props, prop_map, ("condo", "condomínio", "taxa de condomínio"), "condo_fee")
        OLXScraper._set_bool_prop(props, prop_map, ("aceita animais", "aceita_animais", "pets"), "accepts_pets")
        OLXScraper._set_bool_prop(props, prop_map, ("mobiliado", "furnished"), "is_furnished")
        return props

    @staticmethod
    def _detect_listing_type(raw: dict) -> str:
        """Detect if this is a rent or sale listing."""
        # Check URL path for rent/sale indicators
        url = raw.get("url") or raw.get("_olx_url") or ""
        if "aluguel" in url.lower():
            return "rent"
        if "venda" in url.lower():
            return "sale"

        # Check pricingInfos
        pricing = raw.get("pricingInfos") or []
        if isinstance(pricing, list) and pricing:
            first = pricing[0]
            if isinstance(first, dict):
                period = (first.get("period") or "").lower()
                if "month" in period or "mês" in period or "mes" in period:
                    return "rent"
                return "sale"

        # Default: assume rent
        return "rent"

    @staticmethod
    def _neighborhood_from_raw(raw: dict) -> str | None:
        """Best-effort neighborhood extraction."""
        loc = raw.get("location") or {}
        if isinstance(loc, dict):
            return loc.get("neighborhood") or loc.get("neighborhoodName")
        return None
