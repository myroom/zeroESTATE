"""Скрапер коммерческой недвижимости Донстрой (REST API)."""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from scrapers.base_scraper import BaseScraper


class DonstroyScraper(BaseScraper):
    slug = "donstroy"
    name = "Донстрой"
    base_url = "https://donstroy.moscow/buy-commercial/commercial-objects/"

    API_BASE = "https://donstroy.moscow/api/v1/commercial"
    API_ITEMS = f"{API_BASE}/commercial_filter_api/"
    API_SPECS = f"{API_BASE}/commercial_filter_specs/"
    API_PARAMS = f"{API_BASE}/commercial_filter_params/"

    TIMEOUT = 30
    HEADERS = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": "https://donstroy.moscow/buy-commercial/commercial-objects/",
    }

    def scrape(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(self.HEADERS)

        # Fetch filter params for area/price context
        params_data = self._fetch_params(session)
        if params_data:
            self.logger.info(f"Filter params: {params_data}")

        # Fetch project specs for enrichment
        specs_data = self._fetch_specs(session)
        specs_by_pk = {}
        if specs_data:
            for spec in specs_data:
                pk = spec.get("pk") or spec.get("id")
                if pk:
                    specs_by_pk[str(pk)] = spec
            self.logger.info(f"Loaded {len(specs_by_pk)} project specs")

        # Fetch commercial items
        self.logger.info(f"Fetching items from {self.API_ITEMS}")
        resp = session.get(self.API_ITEMS, timeout=self.TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        total = data.get("total", 0)
        raw_items = data.get("items", [])
        self.logger.info(f"API returned total={total}, items={len(raw_items)}")

        items = []
        for raw in raw_items:
            try:
                item = self._map_item(raw, specs_by_pk, params_data)
                if item:
                    items.append(item)
            except Exception as e:
                self.logger.warning(f"Error mapping item {raw.get('id', '?')}: {e}")

        self.logger.info(f"Total items collected: {len(items)}")
        return items

    def _fetch_params(self, session: requests.Session) -> dict | None:
        """Fetch facets (price range, area range) from the params endpoint."""
        try:
            resp = session.get(self.API_PARAMS, timeout=self.TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.logger.warning(f"Could not fetch filter params: {e}")
            return None

    def _fetch_specs(self, session: requests.Session) -> list | None:
        """Fetch project specs (pk, filter_title, tag_title) for enrichment."""
        try:
            resp = session.get(self.API_SPECS, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # Could be a list or a dict with items key
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                specs = data.get("specs", data)
                if isinstance(specs, dict):
                    # specs: {"projects": [...]} structure
                    return specs.get("projects", specs.get("items", []))
                if isinstance(specs, list):
                    return specs
                return []
            return None
        except Exception as e:
            self.logger.warning(f"Could not fetch specs: {e}")
            return None

    def _map_item(self, raw: dict, specs: dict, params: dict | None) -> dict | None:
        """Map a single API item to the PropertySnapshot field set."""
        external_id = str(raw.get("id", ""))
        if not external_id:
            return None

        name = raw.get("name", "").strip()
        purpose = raw.get("purpose", "").strip()
        info = raw.get("info", "").strip()

        # Price extraction
        price_str, price_value = self._extract_price(raw)

        # Area extraction
        area = self._extract_float(raw, "area", "total_area", "UF_AREA")

        # Price per sqm
        price_per_sqm = None
        if price_value and area and area > 0:
            price_per_sqm = int(price_value / area)

        # Floor
        floor = self._extract_int(raw, "floor", "UF_FLOOR")
        floor_total = self._extract_int(raw, "floor_total", "UF_FLOOR_TOTAL", "floors")

        # Images
        image_url = raw.get("image", raw.get("img", raw.get("photo", ""))) or ""
        images = raw.get("images", raw.get("photos", raw.get("gallery", [])))
        if not isinstance(images, list):
            images = []

        # Completion date
        completion = raw.get("completion_date", raw.get("deadline", "")) or ""

        # Status
        status = raw.get("status", "") or ""

        # Build property URL
        obj_id = raw.get("UF_CONSTRUCTION_OBJECT_ID", "")
        property_url = raw.get("url", raw.get("link", "")) or ""
        if not property_url and external_id:
            property_url = f"{self.base_url}?id={external_id}"

        # Spec enrichment
        spec = specs.get(external_id, {})
        project_name = name
        if spec.get("filter_title"):
            project_name = spec["filter_title"]

        # Property type mapping
        property_type = purpose if purpose else "коммерческое"

        # Raw data for debugging / future use
        raw_data = dict(raw)
        if params:
            raw_data["_filter_params"] = params
        if spec:
            raw_data["_spec"] = spec

        return {
            "external_id": external_id,
            "title": name,
            "project_name": project_name,
            "address": info,
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "property_type": property_type,
            "property_url": property_url,
            "status": status,
            "floor": floor,
            "floor_total": floor_total,
            "completion_date": completion,
            "image_url": image_url,
            "images": images,
            "raw_data": raw_data,
        }

    @staticmethod
    def _extract_price(raw: dict) -> tuple[str, int | None]:
        """Extract price string and numeric value from the API item."""
        # Try known fields
        for key in ("price", "price_value", "UF_PRICE", "cost"):
            val = raw.get(key)
            if val is None:
                continue
            if isinstance(val, (int, float)) and val > 0:
                return str(int(val)), int(val)
            if isinstance(val, str):
                cleaned = val.strip()
                if not cleaned:
                    continue
                if "запрос" in cleaned.lower():
                    return "по запросу", None
                # Strip non-digit chars (spaces, currency symbols) and parse
                digits = re.sub(r"[^\d]", "", cleaned)
                if digits:
                    numeric = int(digits)
                    if numeric > 0:
                        return str(numeric), numeric

        # Check for price_str or price_text with human text
        for key in ("price_str", "price_text", "priceText"):
            val = raw.get(key)
            if val and isinstance(val, str):
                val = val.strip()
                if "запрос" in val.lower():
                    return "по запросу", None
                digits = re.sub(r"[^\d]", "", val)
                if digits:
                    numeric = int(digits)
                    if numeric > 0:
                        return str(numeric), numeric

        return "по запросу", None

    @staticmethod
    def _extract_float(raw: dict, *keys: str) -> float | None:
        for key in keys:
            val = raw.get(key)
            if val is None:
                continue
            try:
                f = float(val)
                if f > 0:
                    return f
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _extract_int(raw: dict, *keys: str) -> int | None:
        for key in keys:
            val = raw.get(key)
            if val is None:
                continue
            try:
                i = int(val)
                if i > 0:
                    return i
            except (ValueError, TypeError):
                pass
        return None


if __name__ == "__main__":
    DonstroyScraper().loop()
