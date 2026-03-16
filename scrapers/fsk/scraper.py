"""Скрапер коммерческой недвижимости ФСК (REST API)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
import logging

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("fsk")

API_BASE = "https://fsk.ru/api/v3"
COMMERCIAL_URL = f"{API_BASE}/commercial"
PAGE_SIZE = 100

# FSK finishing codes: 0 = без отделки, 1 = с отделкой, 2 = предчистовая
FINISHING_MAP = {
    0: "Без отделки",
    1: "С отделкой",
    2: "Предчистовая",
}

# FSK status codes: 0 = в продаже
STATUS_MAP = {
    0: "в продаже",
    1: "бронь",
    2: "продано",
}


class FSKScraper(BaseScraper):
    slug = "fsk"
    name = "ФСК"
    base_url = "https://fsk.ru/kommercheskaya-nedvizhimost/investments"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://fsk.ru/kommercheskaya-nedvizhimost/investments",
        })

    def scrape(self) -> list[dict]:
        items = self._scrape_commercial_api()
        if not items:
            self.logger.warning("Commercial API returned 0 items, endpoint may have changed")
        self.logger.info(f"Total items collected: {len(items)}")
        return items

    def _scrape_commercial_api(self) -> list[dict]:
        """Fetch all commercial properties via paginated API."""
        items = []
        page = 1

        while True:
            self.logger.info(f"Fetching page {page} (limit={PAGE_SIZE})")
            try:
                resp = self.session.get(
                    COMMERCIAL_URL,
                    params={"page": page, "limit": PAGE_SIZE},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                self.logger.error(f"API request failed on page {page}: {e}")
                break

            api_items = data.get("items", [])
            if not api_items:
                self.logger.info("No more items returned")
                break

            total = data.get("total", "?")
            total_pages = data.get("totalPages", "?")
            self.logger.info(f"Page {page}/{total_pages}, total={total}, got {len(api_items)} items")

            for raw in api_items:
                parsed = self._parse_item(raw)
                if parsed:
                    items.append(parsed)

            has_next = data.get("hasNextPage", False)
            if not has_next:
                break
            page += 1

        return items

    def _parse_item(self, raw: dict) -> dict | None:
        """Parse a single commercial property from API response."""
        external_id = raw.get("externalId") or raw.get("_id", "")
        if not external_id:
            return None

        # Price
        price_value = raw.get("price")
        if price_value and isinstance(price_value, (int, float)) and price_value > 0:
            price_value = int(price_value)
            price_str = str(price_value)
        else:
            price_value = None
            price_str = "по запросу"

        # Price per m2
        price_per_sqm = raw.get("pricePerMeter")
        if price_per_sqm and isinstance(price_per_sqm, (int, float)) and price_per_sqm > 0:
            price_per_sqm = int(price_per_sqm)
        else:
            price_per_sqm = None

        # Area
        area = raw.get("areaTotal")
        if area is not None:
            try:
                area = float(area)
            except (ValueError, TypeError):
                area = None

        # Floor
        floor = raw.get("floorNumber")
        if floor is not None:
            try:
                floor = int(floor)
            except (ValueError, TypeError):
                floor = None

        # Floor total from section
        floor_total = None
        section = raw.get("section")
        if section and isinstance(section, dict):
            floors_count = section.get("floorsCount")
            if floors_count is not None:
                try:
                    floor_total = int(floors_count)
                except (ValueError, TypeError):
                    pass

        # Finishing
        finishing_code = raw.get("finishing")
        finishing = FINISHING_MAP.get(finishing_code, "")
        has_finishing = finishing_code == 1 if finishing_code is not None else None

        # Status
        status_code = raw.get("status")
        status = STATUS_MAP.get(status_code, "")

        # Project info
        project = raw.get("project") or raw.get("complex") or {}
        project_name = project.get("title", "")
        project_slug = project.get("slug", "")
        project_url = f"https://fsk.ru/{project_slug}" if project_slug else ""
        project_img = project.get("img", "")

        # Completion date from corpus
        completion_date = ""
        corpus = raw.get("corpus")
        if corpus and isinstance(corpus, dict):
            date_delivery = corpus.get("dateDelivery", "")
            if date_delivery:
                completion_date = self._format_delivery_date(date_delivery)

        # Labels may have completion info too
        labels = raw.get("labels", [])
        if not completion_date and labels:
            for label in labels:
                title = label.get("title", "")
                if any(q in title.lower() for q in ["кв ", "квартал", "сдан"]):
                    completion_date = title
                    break

        # Title / number
        number = raw.get("number", "")
        title = f"Пом. {number}" if number else ""

        # Property URL
        property_url = (
            f"https://fsk.ru/kommercheskaya-nedvizhimost/{project_slug}/{external_id}"
            if project_slug else ""
        )

        # Image
        image_url = project_img
        media = project.get("media")
        if media and isinstance(media, dict):
            src = media.get("src", "")
            if src:
                image_url = src

        # Discount info
        discount = raw.get("discount", 0)

        return {
            "external_id": str(external_id),
            "project_name": project_name,
            "project_url": project_url,
            "title": title,
            "property_url": property_url,
            "property_type": "коммерческое",
            "status": status,
            "address": "",
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "floor": floor,
            "floor_total": floor_total,
            "finishing": finishing,
            "has_finishing": has_finishing,
            "completion_date": completion_date,
            "image_url": image_url,
            "raw_data": raw,
        }

    @staticmethod
    def _format_delivery_date(iso_date: str) -> str:
        """Convert ISO date like '2027-03-31T...' to '1 кв 2027'."""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            quarter = (dt.month - 1) // 3 + 1
            return f"{quarter} кв {dt.year}"
        except (ValueError, AttributeError):
            return iso_date


if __name__ == "__main__":
    FSKScraper().loop()
