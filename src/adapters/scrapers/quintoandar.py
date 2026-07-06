"""
QuintoAndar scraper implementation.
Uses HTML parsing to extract the Next.js `__NEXT_DATA__` state, bypassing the need for complex API anti-bot tokens.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator
from bs4 import BeautifulSoup

from adapters.scrapers.base import BaseScraper
from adapters.scrapers.registry import ScraperRegistry
from infra.logging import get_logger

logger = get_logger(__name__)


@ScraperRegistry.register("quintoandar")
class QuintoAndarScraper(BaseScraper):
    """Scrapes properties from QuintoAndar using page iteration."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.city_slug = config.get("city_slug", "belo-horizonte-mg-brasil")

    def start(self) -> None:
        pass

    def fetch_pages(self, checkpoint: Any = None) -> Iterator[Dict[str, Any]]:
        """Fetch properties by iterating over pages until no more are found."""
        if not isinstance(checkpoint, dict):
            checkpoint = {}
            
        start_page = int(checkpoint.get("page", 1))
        scrape_type = checkpoint.get("scrape_type", "both")
        
        base_urls = []
        if scrape_type in ("rent", "both"):
            base_urls.append(f"https://www.quintoandar.com.br/alugar/imovel/{self.city_slug}")
        if scrape_type in ("sale", "both"):
            base_urls.append(f"https://www.quintoandar.com.br/comprar/imovel/{self.city_slug}")

        for base_url in base_urls:
            page = start_page
            while True:
                logger.info("quintoandar_fetching_page", page=page, base_url=base_url)
                url = f"{base_url}?page={page}"
                response = self._throttled_request('GET', url)
                
                if response.status_code != 200:
                    logger.error("quintoandar_http_error", status_code=response.status_code, text=response.text[:200])
                    break
    
                soup = BeautifulSoup(response.text, 'html.parser')
                script = soup.find('script', id='__NEXT_DATA__')
                
                if not script:
                    logger.warning("quintoandar_no_next_data", page=page)
                    break
                    
                try:
                    data = json.loads(script.string)
                    state = data['props']['pageProps']['initialState']
                    houses = state.get('houses', {})
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.error("quintoandar_parse_error", error=str(exc))
                    break
    
                if not houses:
                    logger.info("quintoandar_no_more_houses", page=page)
                    break
    
                # Yield each house
                for property_id, house_data in houses.items():
                    if isinstance(house_data, dict):
                        house_data['page'] = page
                        yield house_data
    
                page += 1
            
            # Reset start_page for the next base_url if applicable
            start_page = 1

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert QuintoAndar JSON into our internal PropertyCandidate format."""
        address_dict = raw.get("address", {})
        
        # Build a full address string
        addr_parts = []
        if address_dict.get("address"):
            addr_parts.append(address_dict["address"])
        if address_dict.get("neighborhood"):
            addr_parts.append(address_dict["neighborhood"])
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
        rent_price = float(raw.get("rentPrice") or 0.0)
        sale_price = float(raw.get("salePrice") or 0.0)
        is_rent = rent_price > 0
        is_sale = sale_price > 0
        
        # Default to rent price if available, otherwise sale price
        price = rent_price if is_rent else sale_price

        # Extract location
        loc = raw.get("location", {})
        lat = float(loc.get("lat") or 0.0)
        lon = float(loc.get("lon") or loc.get("lng") or 0.0)

        # Create discrete listings for the dedupe engine
        listings = []
        base_url = f"https://www.quintoandar.com.br/imovel/{raw.get('id', '')}"
        if is_rent:
            listings.append({
                "platform": "quintoandar",
                "platform_id": str(raw.get("id", "")),
                "listing_type": "rent",
                "price": rent_price,
                "url": base_url
            })
        if is_sale:
            listings.append({
                "platform": "quintoandar",
                "platform_id": str(raw.get("id", "")),
                "listing_type": "sale",
                "price": sale_price,
                "url": base_url
            })

        # Build property candidate
        return {
            "platform": "quintoandar",
            "platform_id": str(raw.get("id", "")),
            "title": raw.get("type", "Imóvel") + f" em {address_dict.get('neighborhood', 'Belo Horizonte')}",
            "description": raw.get("description", ""),
            "price": price,
            "area_m2": float(raw.get("area") or 0.0),
            "bedrooms": int(raw.get("bedrooms") or 0),
            "bathrooms": int(raw.get("bathrooms") or 0),
            "parking": int(raw.get("parkingSpaces") or 0),
            "location": {"lat": lat, "lon": lon},
            "address": address_str,
            "image_urls": image_urls,
            "props_json": {
                "raw_type": raw.get("type"),
                "condo_fee": raw.get("condoFee"),
                "iptu": raw.get("iptu"),
                "is_furnished": raw.get("isFurnished"),
                "neighborhood": address_dict.get("neighborhood"),
            },
            "listings": listings
        }
