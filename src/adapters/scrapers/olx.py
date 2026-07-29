"""
OLX Brazil scraper implementation.

Scrapes real-estate listings from olx.com.br by parsing the embedded
``__NEXT_DATA__`` JSON state, following the same pattern as QuintoAndar.
OLX Brazil serves Next.js pages with structured listing data in the
page's initial state.
"""

from __future__ import annotations

import collections
import json
import random
import re
import time
from typing import Any, Dict, Iterator

from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.common import neighborhoods_for, parse_cities, parse_price_pair
from adapters.scrapers.flight_html import extract_json_array_after as _shared_extract_json_array_after
from adapters.scrapers.flight_html import unescape_js_string as _shared_unescape_js_string
from adapters.scrapers.funnel import bisect_price, listing_id_from_raw, unique_by
from adapters.scrapers.listing_description import extract_olx_description
from adapters.scrapers.redis_circuit_breaker import RedisCircuitBreaker
from adapters.scrapers.registry import ScraperRegistry
from core.exceptions import CircuitBreakerOpenError
from infra.logging import get_logger

logger = get_logger(__name__)

_NON_DIGIT_RE = re.compile(r"[^\d]")

# (category_path, min_p, max_p, zone|None, bairro|None)
_OlxWindow = tuple[str, int, int, str | None, str | None]


@ScraperRegistry.register("olx")
class OLXScraper(BaseScraper):
    """Scrapes properties from OLX Brazil using adaptive price/geo funneling."""

    _BASE_URL = "https://www.olx.com.br/imoveis"

    def __init__(self, platform_name: str, config: Dict[str, Any]):
        super().__init__(platform_name, config)
        self._rate_limit = config.get("rate_limit", 20)
        self._jitter_min = config.get("jitter_min", 2)
        self._jitter_max = config.get("jitter_max", 6)
        extra = config.get("extra") or {}
        self._max_pages = int(extra.get("max_pages", 5))
        self._page_size_hint = int(extra.get("page_size_hint", 50))
        self._price_rent = parse_price_pair(extra.get("price_rent"), (500, 15000))
        self._price_sale = parse_price_pair(extra.get("price_sale"), (100000, 5000000))
        cities = parse_cities(
            extra,
            {"region": "estado-mg", "city_slug": "belo-horizonte-e-regiao"},
            require_zone=True,
        )
        self._RENT_PATHS: list[str] = []
        self._SALE_PATHS: list[str] = []
        self._path_neighborhoods: dict[str, list[dict[str, str]]] = {}
        for city in cities:
            region = city["region"]
            city_slug = city["city_slug"]
            neighborhoods = city["neighborhoods"]
            rent_paths = [
                f"aluguel/apartamentos/{region}/{city_slug}",
                f"aluguel/casas/{region}/{city_slug}",
            ]
            sale_paths = [
                f"venda/apartamentos/{region}/{city_slug}",
                f"venda/casas/{region}/{city_slug}",
            ]
            self._RENT_PATHS.extend(rent_paths)
            self._SALE_PATHS.extend(sale_paths)
            for path in rent_paths + sale_paths:
                self._path_neighborhoods[path] = neighborhoods
        # Back-compat for tests that mutate ``_neighborhoods`` (first city).
        self._neighborhoods = list(cities[0]["neighborhoods"]) if cities else []

    def _neighborhoods_for_path(self, path: str) -> list[dict[str, str]]:
        return neighborhoods_for(self._path_neighborhoods, path, self._neighborhoods)

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

    def fetch_description(self, url: str) -> str:
        """GET a detail page and extract the ad body / description."""
        if not (url or "").strip():
            return ""
        try:
            response = self._throttled_request(url)
        except CircuitBreakerOpenError:
            logger.warning("olx_description_circuit_open", url=url)
            return ""
        except Exception as exc:  # detail enrich must not abort scrape
            logger.warning("olx_description_fetch_error", url=url, error=str(exc))
            return ""
        if response.status_code != 200:
            logger.info(
                "olx_description_http",
                url=url,
                status_code=response.status_code,
            )
            return ""
        text = extract_olx_description(response.text or "")
        if not text:
            logger.info("olx_description_empty", url=url)
        return text

    # ------------------------------------------------------------------
    # fetch_pages — adaptive price / geo funnel
    # ------------------------------------------------------------------

    def fetch_pages(self, checkpoint: Any = None) -> Iterator[Dict[str, Any]]:
        """Yield raw listing dicts via price-first BFS with geo fan-out.

        City-wide windows paginate with ``ps``/``pe``. When a window hits
        ``max_pages`` with a full last page, the price band is bisected; if
        the band is atomic, configured neighborhoods are enqueued instead.
        """
        if not isinstance(checkpoint, dict):
            checkpoint = {}

        queue: collections.deque[_OlxWindow] = collections.deque(
            self._initial_windows(checkpoint)
        )
        visited: set[_OlxWindow] = set()
        kept_by_id: dict[str, dict] = {}

        while queue:
            window = queue.popleft()
            if window in visited:
                continue
            visited.add(window)
            path, min_p, max_p, zone, bairro = window
            collected, saturated = self._fetch_window(path, min_p, max_p, zone, bairro)
            if not collected and not saturated:
                continue
            if saturated:
                halves = bisect_price(min_p, max_p)
                if halves:
                    (lo_a, hi_a), (lo_b, hi_b) = halves
                    queue.append((path, lo_a, hi_a, zone, bairro))
                    queue.append((path, lo_b, hi_b, zone, bairro))
                    logger.info(
                        "olx_splitting_price_window",
                        path=path,
                        min_p=min_p,
                        max_p=max_p,
                        zone=zone,
                        bairro=bairro,
                    )
                    continue
                if zone is None:
                    neighborhoods = self._neighborhoods_for_path(path)
                    if neighborhoods:
                        for nb in neighborhoods:
                            queue.append(
                                (path, min_p, max_p, nb["zone"], nb["slug"])
                            )
                        logger.info(
                            "olx_fanout_neighborhoods",
                            path=path,
                            min_p=min_p,
                            max_p=max_p,
                            count=len(neighborhoods),
                        )
                        continue
                logger.warning(
                    "olx_window_truncated",
                    path=path,
                    min_p=min_p,
                    max_p=max_p,
                    zone=zone,
                    bairro=bairro,
                    collected=len(collected),
                )

            for listing in self._yield_merged_listings(collected, kept_by_id):
                yield listing

    def _initial_windows(self, checkpoint: dict) -> list[_OlxWindow]:
        scrape_type = checkpoint.get("scrape_type", "both")
        paths: list[str] = []
        if scrape_type in ("rent", "both"):
            paths.extend(self._RENT_PATHS)
        if scrape_type in ("sale", "both"):
            paths.extend(self._SALE_PATHS)
        windows: list[_OlxWindow] = []
        for path in paths:
            min_p, max_p = self._price_band_for_path(path)
            windows.append((path, min_p, max_p, None, None))
        return windows

    def _price_band_for_path(self, path: str) -> tuple[int, int]:
        if path.startswith("aluguel"):
            return self._price_rent
        return self._price_sale

    def _build_search_url(
        self,
        path: str,
        page: int,
        min_p: int,
        max_p: int,
        zone: str | None,
        bairro: str | None,
    ) -> str:
        geo = f"{path}/{zone}/{bairro}" if zone and bairro else path
        return f"{self._BASE_URL}/{geo}?ps={min_p}&pe={max_p}&o={page}"

    def _fetch_window(
        self,
        path: str,
        min_p: int,
        max_p: int,
        zone: str | None,
        bairro: str | None,
    ) -> tuple[list[dict], bool]:
        """Return (listings, saturated). Saturated = hit max_pages with a full last page."""
        collected: list[dict] = []
        last_page_count = 0
        pages_fetched = 0
        for page in range(1, self._max_pages + 1):
            url = self._build_search_url(path, page, min_p, max_p, zone, bairro)
            listings = self._fetch_page_listings(url, page)
            pages_fetched += 1
            if not listings:
                break
            last_page_count = len(listings)
            window_type = self._listing_type_from_category_path(path)
            window_property_type = self._property_type_from_category_path(path)
            for listing in listings:
                listing["_olx_url"] = url
                if window_type:
                    listing["_olx_listing_type"] = window_type
                if window_property_type:
                    listing["_olx_property_type"] = window_property_type
                collected.append(listing)
        # Hit the page ceiling with a near-full last page → more inventory likely.
        # Requiring an exact page_size_hint missed common partial last pages (~40/50)
        # and stopped city windows near ~200 without fan-out. Keep a strict
        # threshold for tiny test hints (<10) so atomic children still yield.
        if self._page_size_hint >= 10:
            full_enough = max(1, int(self._page_size_hint * 0.7))
        else:
            full_enough = self._page_size_hint
        saturated = pages_fetched >= self._max_pages and last_page_count >= full_enough
        return collected, saturated

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
        listings = self._parse_listings_html(response.text, url=url)
        if listings:
            logger.info("olx_page_listings", url=url, page=page, count=len(listings))
        else:
            logger.debug("olx_no_listings_in_page", url=url, page=page)
        return listings

    def _parse_listings_html(self, html: str, url: str = "") -> list[dict]:
        """Extract listing dicts from classic __NEXT_DATA__ or Flight RSC HTML."""
        script = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                listings = self._extract_listings(json.loads(script.string))
                if listings:
                    return listings
            except (json.JSONDecodeError, TypeError):
                logger.exception("olx_json_parse_error", url=url)

        listings = self._extract_flight_ads(html)
        if listings:
            return listings

        logger.warning("olx_no_listing_payload", url=url)
        return []

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
                return self._filter_ad_dicts(obj)

        # Strategy 2: pageProps directly has ads/data list
        for key in ("ads", "listings", "data"):
            val = page_props.get(key)
            if isinstance(val, list):
                return self._filter_ad_dicts(val)

        return []

    @staticmethod
    def _filter_ad_dicts(items: list) -> list[dict]:
        """Keep real listing objects; drop ad-slot / non-dict noise."""
        out: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("advertisingId") and not (
                item.get("listId") or item.get("list_id") or item.get("id")
            ):
                continue
            if not (item.get("listId") or item.get("list_id") or item.get("id")):
                continue
            out.append(item)
        return out

    @staticmethod
    def _unescape_js_string(value: str) -> str:
        """Decode escapes used inside ``self.__next_f.push([1, \"...\"])`` payloads."""
        return _shared_unescape_js_string(value)

    @staticmethod
    def _extract_json_array_after(haystack: str, marker: str) -> list | None:
        """Return the JSON array that follows ``marker`` (e.g. ``\"ads\":``)."""
        return _shared_extract_json_array_after(haystack, marker)

    def _extract_flight_ads(self, html: str) -> list[dict]:
        """Parse listing ads embedded in Next.js Flight (``__next_f.push``) payloads.

        OLX listing pages no longer ship ``__NEXT_DATA__``; ads arrive as an
        ``\"ads\":[...]`` array inside streamed RSC chunks.
        """
        push_re = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
        for match in push_re.finditer(html):
            raw = match.group(1)
            if "listId" not in raw or ("ads" not in raw and "priceValue" not in raw):
                continue
            chunk = self._unescape_js_string(raw)
            for marker in ('"ads":', '"ads" :'):
                parsed = self._extract_json_array_after(chunk, marker)
                if parsed:
                    listings = self._filter_ad_dicts(parsed)
                    if listings:
                        return listings
        return []

    # ------------------------------------------------------------------
    # Cross-window dual rent+sale merge (BIN-108)
    # ------------------------------------------------------------------

    def _yield_merged_listings(
        self,
        collected: list[dict],
        kept_by_id: dict[str, dict],
    ) -> Iterator[Dict[str, Any]]:
        """Yield new listings; re-yield when a second listing type merges in."""
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
        """Merge rent+sale prices when the same listId appears in both windows.

        Mutates ``kept`` with ``_olx_prices`` and clears ``_olx_listing_type``
        when both sides are present. Returns True when a merge happened.
        """
        kept_type = kept.get("_olx_listing_type")
        incoming_type = incoming.get("_olx_listing_type")
        if kept_type not in ("rent", "sale") or incoming_type not in ("rent", "sale"):
            return False
        if kept_type == incoming_type:
            return False

        prices = dict(kept.get("_olx_prices") or {})
        for raw, kind in ((kept, kept_type), (incoming, incoming_type)):
            try:
                prices[kind] = OLXScraper._parse_price(raw)
            except (TypeError, ValueError):
                return False
        if "rent" not in prices or "sale" not in prices:
            return False
        kept["_olx_prices"] = prices
        kept.pop("_olx_listing_type", None)
        return True

    # ------------------------------------------------------------------
    # normalize — convert raw OLX listing to PropertyCandidate format
    # ------------------------------------------------------------------

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an OLX listing dict into the internal PropertyCandidate format."""

        # --- Platform ID ---
        platform_id = str(
            raw.get("list_id")
            or raw.get("listId")
            or raw.get("id")
            or raw.get("ad_id")
            or ""
        )
        if not platform_id:
            raise ValueError("OLX listing missing id/list_id")

        # --- Title ---
        title = raw.get("subject") or raw.get("title") or "Imóvel"

        # --- Description ---
        # Flight search ads omit body; detail enrich fills this later (BIN-105).
        description = (raw.get("body") or raw.get("description") or "").strip()

        # --- Location ---
        location_dict, address_str = self._parse_location(raw)

        # --- Images ---
        image_urls = self._parse_images(raw)

        # --- Property attributes ---
        props = self._parse_properties(raw)

        rent_base, sale_price = self._prices_for_listing(raw)
        condo = float(props.get("condo_fee") or 0.0)
        iptu = float(props.get("iptu") or 0.0)
        rent_total = (rent_base + condo + iptu) if rent_base is not None else None

        listing_url = (
            raw.get("url") or raw.get("_olx_url") or f"https://www.olx.com.br/detalhes/{platform_id}"
        )
        # OLX exposes Condomínio and IPTU as separate labeled props — never invent a
        # bundle or split (BIN-114). Always stamp fees_bundled=false for projection/UI.
        base_listing = {
            "platform": "olx",
            "platform_listing_id": platform_id,
            "currency": "BRL",
            "url": listing_url,
            "is_furnished": props.get("is_furnished"),
            "accepts_pets": props.get("accepts_pets"),
            "condo_fee": props.get("condo_fee"),
            "iptu": props.get("iptu"),
            "raw_json": {"fees_bundled": False},
        }
        listings: list[dict] = []
        if rent_total is not None and rent_total > 0:
            listings.append(
                {
                    **base_listing,
                    "listing_type": "rent",
                    "price": rent_total,
                    "base_price": rent_base,
                }
            )
        if sale_price is not None and sale_price > 0:
            listings.append(
                {
                    **base_listing,
                    "listing_type": "sale",
                    "price": sale_price,
                    "base_price": None,
                }
            )
        if not listings:
            raise ValueError(
                "Could not parse price from OLX listing: "
                f"{raw.get('listId', raw.get('list_id', raw.get('id', '?')))}"
            )

        is_rent = rent_total is not None and rent_total > 0
        is_sale = sale_price is not None and sale_price > 0
        price = rent_total if is_rent else sale_price

        # --- Neighborhood name ---
        neighborhood = (
            location_dict.get("neighborhood")
            if isinstance(location_dict, dict)
            else None
        ) or self._neighborhood_from_raw(raw)

        loc_details = self._location_details(raw)
        city = loc_details.get("city") or loc_details.get("cityName") or loc_details.get("municipality")
        state = loc_details.get("uf") or loc_details.get("state")

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
                "type": self._detect_property_type(raw),
                "neighborhood": neighborhood,
                "city": city,
                "state": state,
                "available_for_rent": is_rent,
                "available_for_sale": is_sale,
                "isFurnished": props.get("is_furnished"),
                "amenities": [],
            },
            "listings": listings,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prices_for_listing(raw: dict) -> tuple[float | None, float | None]:
        """Return ``(rent_base, sale)`` when known; either side may be None.

        Prefer cross-window ``_olx_prices``, then multi-entry ``pricingInfos``,
        else a single price typed via ``_detect_listing_type``.
        """
        dual = raw.get("_olx_prices")
        if isinstance(dual, dict):
            rent = OLXScraper._positive_number([dual.get("rent")])
            sale = OLXScraper._positive_number([dual.get("sale")])
            if rent is not None or sale is not None:
                return rent, sale

        from_infos = OLXScraper._prices_from_pricing_infos(raw.get("pricingInfos"))
        if from_infos is not None:
            rent, sale = from_infos
            if rent is not None and sale is not None:
                return rent, sale
            if rent is not None or sale is not None:
                # One typed entry — still prefer stamp/path detection when only
                # one side exists so single-entry monthly keeps rent semantics.
                if rent is not None and sale is None:
                    return rent, None
                if sale is not None and rent is None:
                    return None, sale

        price = OLXScraper._parse_price(raw)
        listing_type = OLXScraper._detect_listing_type(raw)
        if listing_type == "rent":
            return price, None
        return None, price

    @staticmethod
    def _prices_from_pricing_infos(
        pricing_infos: Any,
    ) -> tuple[float | None, float | None] | None:
        if not isinstance(pricing_infos, list) or not pricing_infos:
            return None
        rent: float | None = None
        sale: float | None = None
        typed_any = False
        for entry in pricing_infos:
            if not isinstance(entry, dict):
                continue
            amount = OLXScraper._positive_number(
                entry.get(key) for key in ("value", "price")
            )
            if amount is None:
                continue
            kind = OLXScraper._listing_type_from_pricing_entry(entry)
            if kind is None:
                continue
            typed_any = True
            if kind == "rent" and rent is None:
                rent = amount
            elif kind == "sale" and sale is None:
                sale = amount
        if not typed_any:
            return None
        return rent, sale

    @staticmethod
    def _listing_type_from_pricing_entry(entry: dict) -> str | None:
        period = str(entry.get("period") or "").lower()
        business = str(
            entry.get("businessType")
            or entry.get("business_type")
            or entry.get("priceType")
            or ""
        ).lower()
        blob = f"{period} {business}"
        if any(token in blob for token in ("month", "mês", "mes", "rent", "aluguel")):
            return "rent"
        if any(token in blob for token in ("sale", "sell", "venda", "year", "ano")):
            return "sale"
        # Empty period with a sale-band price is treated as sale by callers that
        # already have a second monthly entry; bare empty → sale when alone.
        if period == "" and business == "":
            amount = OLXScraper._positive_number(
                entry.get(key) for key in ("value", "price")
            )
            if amount is not None and amount >= 80_000:
                return "sale"
            if amount is not None and 0 < amount < 30_000:
                return "rent"
        return None

    @staticmethod
    def _parse_price(raw: dict) -> float:
        """Extract numeric price from OLX listing."""
        direct = OLXScraper._positive_number(
            raw.get(key) for key in ("value", "price", "pricingInfos")
        )
        if direct is not None:
            return direct
        pricing_infos = raw.get("pricingInfos")
        if isinstance(pricing_infos, list) and pricing_infos and isinstance(pricing_infos[0], dict):
            nested = OLXScraper._positive_number(
                pricing_infos[0].get(key) for key in ("value", "price")
            )
            if nested is not None:
                return nested
        for key in ("priceValue", "price", "price_str", "value_str", "subject"):
            parsed = OLXScraper._parse_brazilian_number(raw.get(key))
            if parsed is not None:
                return parsed
        raise ValueError(
            "Could not parse price from OLX listing: "
            f"{raw.get('listId', raw.get('list_id', raw.get('id', '?')))}"
        )

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
    def _location_details(raw: dict) -> dict:
        """Normalize location payload (dict, string label, or locationDetails)."""
        details = raw.get("locationDetails")
        if isinstance(details, dict):
            return details
        loc = raw.get("location")
        if isinstance(loc, dict):
            return loc
        return {}

    @staticmethod
    def _address_from_loc(loc: dict, fallback_label: str | None = None) -> str | None:
        parts = []
        for key in ("address", "street"):
            if loc.get(key):
                parts.append(loc[key])
                break
        neighborhood = (
            loc.get("neighborhood")
            or loc.get("neighborhoodName")
            or loc.get("neighbourhood")
        )
        if neighborhood:
            parts.append(neighborhood)
        city = loc.get("city") or loc.get("cityName") or loc.get("municipality")
        if city:
            parts.append(city)
        uf = loc.get("uf") or loc.get("state")
        if uf and (not parts or uf not in str(parts[-1])):
            parts.append(uf)
        if parts:
            return ", ".join(parts)
        return fallback_label or None

    @staticmethod
    def _parse_location(raw: dict) -> tuple:
        """Return (location_dict, address_str)."""
        loc = OLXScraper._location_details(raw)
        lat, lon = OLXScraper._coords_from_raw(raw)
        location_dict = None
        neighborhood = (
            loc.get("neighborhood")
            or loc.get("neighborhoodName")
            or loc.get("neighbourhood")
            or ""
        )
        if lat and lon:
            location_dict = {"lat": lat, "lon": lon, "neighborhood": neighborhood}
        elif neighborhood:
            location_dict = {"neighborhood": neighborhood}
        label = raw.get("location") if isinstance(raw.get("location"), str) else None
        address_str = OLXScraper._address_from_loc(loc, fallback_label=label)
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
                    or img.get("originalWebp")
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
                    value = p.get("value") or p.get("text") or ""
                    for key in (p.get("label"), p.get("name")):
                        label = (key or "").lower()
                        if label and value != "":
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
            parsed = OLXScraper._parse_brazilian_number(str(val))
            if parsed is not None:
                props[dest] = parsed
                break
            try:
                props[dest] = float(re.sub(r"[^\d.]", "", str(val)).replace(",", "."))
            except (ValueError, TypeError):
                continue
            break

    @staticmethod
    def _set_int_prop(props: dict, prop_map: dict, keys: tuple[str, ...], dest: str) -> None:
        for key in keys:
            val = prop_map.get(key)
            if not val:
                continue
            try:
                digits = _NON_DIGIT_RE.sub("", str(val))
                if not digits:
                    continue
                props[dest] = int(digits)
            except (ValueError, TypeError):
                continue
            break

    @staticmethod
    def _set_bool_prop(props: dict, prop_map: dict, keys: tuple[str, ...], dest: str) -> None:
        for key in keys:
            val = prop_map.get(key)
            if val:
                lowered = str(val).lower()
                props[dest] = "sim" in lowered or "permit" in lowered
                break

    @staticmethod
    def _parse_properties(raw: dict) -> dict:
        """Extract property attributes from OLX listing."""
        props = {}
        prop_map = OLXScraper._prop_map_from_raw(raw)
        OLXScraper._set_float_prop(
            props,
            prop_map,
            ("área", "área construída", "area", "area_total", "area_util", "size"),
            "area_m2",
        )
        OLXScraper._set_int_prop(
            props,
            prop_map,
            ("quartos", "dormitórios", "bedrooms", "rooms"),
            "bedrooms",
        )
        OLXScraper._set_int_prop(props, prop_map, ("banheiros", "bathrooms"), "bathrooms")
        OLXScraper._set_int_prop(
            props,
            prop_map,
            (
                "vagas",
                "vagas na garagem",
                "garagem",
                "parking",
                "parking_spaces",
                "garage_spaces",
            ),
            "parking",
        )
        OLXScraper._set_float_prop(
            props,
            prop_map,
            ("condo", "condomínio", "condominio", "taxa de condomínio"),
            "condo_fee",
        )
        OLXScraper._set_float_prop(props, prop_map, ("iptu",), "iptu")
        OLXScraper._set_bool_prop(
            props,
            prop_map,
            (
                "aceita animais",
                "aceita pets",
                "aceita_animais",
                "pets",
                "re_complex_features",
            ),
            "accepts_pets",
        )
        OLXScraper._set_bool_prop(props, prop_map, ("mobiliado", "furnished"), "is_furnished")
        return props

    @staticmethod
    def _listing_type_from_category_path(path: str) -> str | None:
        """Map search category path (or URL) to rent/sale via path segments."""
        lowered = (path or "").lower()
        if "/aluguel/" in lowered or lowered.startswith("aluguel/") or "/alugar/" in lowered:
            return "rent"
        if "/venda/" in lowered or lowered.startswith("venda/"):
            return "sale"
        return None

    @staticmethod
    def _property_type_from_category_path(path: str) -> str | None:
        """Map search category path (or URL) to canonical house type via path segments."""
        from core.property_type import normalize_property_type

        lowered = (path or "").lower()
        # Prefer path segments so zone slugs like ``venda-nova`` are ignored.
        for segment in ("apartamentos", "casas", "kitnets", "kitnet"):
            if f"/{segment}/" in lowered or lowered.startswith(f"{segment}/"):
                return normalize_property_type(segment)
            # Trailing segment without slash (e.g. stamped short path).
            if lowered.endswith(f"/{segment}") or lowered == segment:
                return normalize_property_type(segment)
        return None

    @staticmethod
    def _detect_property_type(raw: dict) -> str | None:
        """Resolve canonical property type for OLX (stamp → URL → prop labels)."""
        from core.property_type import normalize_property_type

        stamped = raw.get("_olx_property_type")
        if stamped:
            return normalize_property_type(str(stamped)) or stamped

        for key in ("url", "_olx_url"):
            from_path = OLXScraper._property_type_from_category_path(str(raw.get(key) or ""))
            if from_path:
                return from_path

        prop_map = OLXScraper._prop_map_from_raw(raw)
        for key in (
            "categoria",
            "category",
            "tipo do imóvel",
            "tipo_do_imovel",
            "tipo do imovel",
            "real_estate_type",
            "property_type",
        ):
            canonical = normalize_property_type(prop_map.get(key))
            if canonical:
                return canonical

        # Title heuristics as last resort (e.g. "Apartamento 2 quartos…").
        from core.property_type import infer_property_type_from_text

        return infer_property_type_from_text(str(raw.get("subject") or raw.get("title") or ""))

    @staticmethod
    def _detect_listing_type(raw: dict) -> str:
        """Detect if this is a rent or sale listing.

        Prefer the search-window stamp (``_olx_listing_type``) because modern
        detail URLs often omit ``/venda/`` or ``/aluguel/``. Path-segment checks
        avoid false positives from zone slugs like ``venda-nova``. When those
        are missing, use title cues (Venda Nova–safe) and price band before
        defaulting to sale (BIN-81).
        """
        from core.olx_listing_type import (
            infer_olx_listing_type,
            mask_venda_nova,
        )

        stamped = raw.get("_olx_listing_type")
        if stamped in ("rent", "sale"):
            return stamped

        for key in ("url", "_olx_url"):
            from_path = OLXScraper._listing_type_from_category_path(str(raw.get(key) or ""))
            if from_path:
                return from_path

        prop_map = OLXScraper._prop_map_from_raw(raw)
        tipo = str(prop_map.get("tipo") or prop_map.get("real_estate_type") or "").lower()
        # Mask neighbourhood so tipo/value junk containing "venda nova" is safe.
        tipo_masked = mask_venda_nova(tipo).casefold()
        if "aluguel" in tipo_masked or "alugar" in tipo_masked:
            return "rent"
        if "venda" in tipo_masked or "vender" in tipo_masked:
            return "sale"

        pricing = raw.get("pricingInfos") or []
        if isinstance(pricing, list) and pricing:
            first = pricing[0]
            if isinstance(first, dict):
                period = (first.get("period") or "").lower()
                if "month" in period or "mês" in period or "mes" in period:
                    return "rent"

        title = str(raw.get("subject") or raw.get("title") or "")
        price: float | None = None
        try:
            price = OLXScraper._parse_price(raw)
        except (TypeError, ValueError):
            price = None

        return infer_olx_listing_type(title=title, price=price, current="sale")

    @staticmethod
    def _neighborhood_from_raw(raw: dict) -> str | None:
        """Best-effort neighborhood extraction."""
        details = OLXScraper._location_details(raw)
        if details:
            return (
                details.get("neighborhood")
                or details.get("neighborhoodName")
                or details.get("neighbourhood")
            )
        loc = raw.get("location")
        if isinstance(loc, dict):
            return loc.get("neighborhood") or loc.get("neighborhoodName")
        return None
