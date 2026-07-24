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
from adapters.scrapers.funnel import bisect_price, listing_id_from_raw, unique_by
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
        region = extra.get("region", "estado-mg")
        city_slug = extra.get("city_slug", "belo-horizonte-e-regiao")
        self._price_rent = self._parse_price_pair(extra.get("price_rent"), (500, 15000))
        self._price_sale = self._parse_price_pair(extra.get("price_sale"), (100000, 5000000))
        self._neighborhoods = self._parse_neighborhoods(extra.get("neighborhoods") or [])
        # Category paths only (no -e-regiao duplicate); geo fan-out adds zone/bairro.
        self._RENT_PATHS = [
            f"aluguel/apartamentos/{region}/{city_slug}",
            f"aluguel/casas/{region}/{city_slug}",
        ]
        self._SALE_PATHS = [
            f"venda/apartamentos/{region}/{city_slug}",
            f"venda/casas/{region}/{city_slug}",
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
    def _parse_neighborhoods(raw: list) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            zone = item.get("zone")
            if slug and zone:
                out.append({"slug": str(slug), "zone": str(zone)})
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
        seen_ids: set[str] = set()

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
                if zone is None and self._neighborhoods:
                    for nb in self._neighborhoods:
                        queue.append((path, min_p, max_p, nb["zone"], nb["slug"]))
                    logger.info(
                        "olx_fanout_neighborhoods",
                        path=path,
                        min_p=min_p,
                        max_p=max_p,
                        count=len(self._neighborhoods),
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

            for listing in unique_by(collected, listing_id_from_raw, seen=seen_ids):
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
            for listing in listings:
                listing["_olx_url"] = url
                collected.append(listing)
        saturated = (
            pages_fetched >= self._max_pages
            and last_page_count >= self._page_size_hint
        )
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
        out: list[str] = []
        i = 0
        while i < len(value):
            ch = value[i]
            if ch == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                if nxt == "n":
                    out.append("\n")
                    i += 2
                elif nxt == "r":
                    out.append("\r")
                    i += 2
                elif nxt == "t":
                    out.append("\t")
                    i += 2
                elif nxt == '"':
                    out.append('"')
                    i += 2
                elif nxt == "\\":
                    out.append("\\")
                    i += 2
                elif nxt == "u" and i + 5 < len(value):
                    try:
                        out.append(chr(int(value[i + 2 : i + 6], 16)))
                        i += 6
                    except ValueError:
                        out.append(nxt)
                        i += 2
                else:
                    out.append(nxt)
                    i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    @staticmethod
    def _extract_json_array_after(haystack: str, marker: str) -> list | None:
        """Return the JSON array that follows ``marker`` (e.g. ``\"ads\":``)."""
        idx = haystack.find(marker)
        if idx < 0:
            return None
        start = haystack.find("[", idx + len(marker))
        if start < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for pos in range(start, len(haystack)):
            ch = haystack[pos]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(haystack[start : pos + 1])
                    except json.JSONDecodeError:
                        return None
                    return parsed if isinstance(parsed, list) else None
        return None

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
            ("aceita animais", "aceita_animais", "pets", "re_complex_features"),
            "accepts_pets",
        )
        OLXScraper._set_bool_prop(props, prop_map, ("mobiliado", "furnished"), "is_furnished")
        return props

    @staticmethod
    def _detect_listing_type(raw: dict) -> str:
        """Detect if this is a rent or sale listing."""
        url = (raw.get("url") or raw.get("_olx_url") or "").lower()
        if "aluguel" in url or "/alugar" in url:
            return "rent"
        if "venda" in url:
            return "sale"

        prop_map = OLXScraper._prop_map_from_raw(raw)
        tipo = str(prop_map.get("tipo") or prop_map.get("real_estate_type") or "").lower()
        if "aluguel" in tipo or "alugar" in tipo:
            return "rent"
        if "venda" in tipo or "vender" in tipo:
            return "sale"

        pricing = raw.get("pricingInfos") or []
        if isinstance(pricing, list) and pricing:
            first = pricing[0]
            if isinstance(first, dict):
                period = (first.get("period") or "").lower()
                if "month" in period or "mês" in period or "mes" in period:
                    return "rent"
                return "sale"

        return "rent"

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
