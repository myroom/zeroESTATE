"""Скрапер коммерческой недвижимости ПИК (REST API)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
import logging

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("pik")

API_URL = "https://api-selectel.pik.ru/v2/filter"
BASE_PARAMS = {
    "types": 1,
    "flatTypes": 5,
    "isCommercial": "true",
    "location": 2,
}
PAGE_SIZE = 20


class PikScraper(BaseScraper):
    slug = "pik"
    name = "ПИК"
    base_url = "https://www.pik.ru/business/projects"

    def scrape(self) -> list[dict]:
        items = []
        offset = 0

        while True:
            params = {**BASE_PARAMS, "offset": offset, "limit": PAGE_SIZE}
            self.logger.info(f"Fetching offset={offset} limit={PAGE_SIZE}")

            resp = requests.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            blocks = data.get("blocks", [])
            if not blocks:
                break

            page_has_flats = False
            for block in blocks:
                flats = block.get("flats", [])
                if not flats:
                    continue
                page_has_flats = True

                block_name = block.get("name", "")
                block_url = block.get("url", "")
                block_metro = block.get("metro", "")
                block_time_on_foot = block.get("timeOnFoot")
                block_lat = block.get("latitude")
                block_lon = block.get("longitude")

                # First image from block
                block_images = block.get("images", [])
                first_image = ""
                if block_images and isinstance(block_images, list):
                    img = block_images[0]
                    if isinstance(img, dict):
                        first_image = img.get("url", "") or img.get("src", "")
                    elif isinstance(img, str):
                        first_image = img

                project_url = f"https://www.pik.ru{block_url}" if block_url else ""

                for flat in flats:
                    flat_id = flat.get("id")
                    if not flat_id:
                        continue

                    flat_price = flat.get("price")
                    price_value = int(flat_price) if flat_price else None
                    price_str = str(flat_price) if flat_price else "по запросу"
                    if price_value == 0:
                        price_str = "по запросу"
                        price_value = None

                    meter_price = flat.get("meterPrice")
                    price_per_sqm = int(meter_price) if meter_price else None

                    ceiling_height = flat.get("ceilingHeight")
                    if ceiling_height is not None:
                        try:
                            ceiling_height = float(ceiling_height)
                        except (ValueError, TypeError):
                            ceiling_height = None

                    area = flat.get("area")
                    if area is not None:
                        try:
                            area = float(area)
                        except (ValueError, TypeError):
                            area = None

                    floor = flat.get("floor")
                    if floor is not None:
                        try:
                            floor = int(floor)
                        except (ValueError, TypeError):
                            floor = None

                    time_on_foot = None
                    if block_time_on_foot is not None:
                        try:
                            time_on_foot = int(block_time_on_foot)
                        except (ValueError, TypeError):
                            time_on_foot = None

                    items.append({
                        "project_name": block_name,
                        "project_url": project_url,
                        "title": flat.get("name", ""),
                        "property_url": flat.get("url", ""),
                        "property_type": "коммерческое",
                        "status": flat.get("status", ""),
                        "address": flat.get("address", ""),
                        "metro_station": block_metro,
                        "metro_distance_min": time_on_foot,
                        "latitude": block_lat,
                        "longitude": block_lon,
                        "area": area,
                        "price": price_str,
                        "price_value": price_value,
                        "price_per_sqm": price_per_sqm,
                        "floor": floor,
                        "ceiling_height": ceiling_height,
                        "has_finishing": flat.get("finish"),
                        "image_url": first_image,
                        "external_id": str(flat_id),
                        "raw_data": flat,
                    })

            # If no flats found in any block on this page, stop
            if not page_has_flats:
                break

            # If fewer blocks than PAGE_SIZE, we've reached the last page
            if len(blocks) < PAGE_SIZE:
                break

            offset += PAGE_SIZE

        self.logger.info(f"Total flats collected: {len(items)}")
        return items


if __name__ == "__main__":
    scraper = PikScraper()
    scraper.loop()
