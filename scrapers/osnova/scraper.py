"""Скрапер коммерческой недвижимости ГК ОСНОВА (REST API)."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import re
import requests
import logging

from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("osnova")

API_BASE = "https://api.gkosnova.tech/public/api/v1"
PROJECTS_URL = f"{API_BASE}/building-objects/projects"

# Additional endpoints to probe for commercial/office data
PROBE_ENDPOINTS = [
    f"{API_BASE}/building-objects/offices",
    f"{API_BASE}/building-objects/commercial",
    f"{API_BASE}/commercial/",
    f"{API_BASE}/offices/",
    f"{API_BASE}/building-objects/projects?type=commercial",
    f"{API_BASE}/building-objects/projects?type=office",
    f"{API_BASE}/building-objects/flats?type=commercial",
    f"{API_BASE}/building-objects/flats?type=office",
]

SITE_BASE = "https://gk-osnova.ru"


class OsnovaScraper(BaseScraper):
    slug = "osnova"
    name = "ГК ОСНОВА"
    base_url = "https://gk-osnova.ru/emotion/offices"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })

    def scrape(self) -> list[dict]:
        items = []

        # Strategy 1: Probe dedicated commercial/office endpoints
        items = self._probe_commercial_endpoints()
        if items:
            self.logger.info(f"Got {len(items)} items from dedicated commercial endpoint")
            return items

        # Strategy 2: Fetch projects and extract non-apartment (commercial/office) flats
        self.logger.info("Probing did not yield results, fetching from projects endpoint")
        items = self._scrape_from_projects()

        if not items:
            self.logger.warning("No commercial properties found. "
                                "The API may have changed or no commercial listings are available.")

        self.logger.info(f"Total items collected: {len(items)}")
        return items

    def _probe_commercial_endpoints(self) -> list[dict]:
        """Try various API endpoints that might serve commercial listings directly."""
        for endpoint in PROBE_ENDPOINTS:
            self.logger.info(f"Probing endpoint: {endpoint}")
            try:
                resp = self.session.get(endpoint, timeout=30)
                self.logger.info(f"  Status: {resp.status_code}, "
                                 f"Content-Type: {resp.headers.get('Content-Type', '')}")
                if resp.status_code == 200:
                    data = resp.json()
                    self.logger.info(f"  Response type: {type(data).__name__}, "
                                     f"keys: {list(data.keys()) if isinstance(data, dict) else f'list[{len(data)}]'}")
                    items = self._parse_list_response(data, project_context=None)
                    if items:
                        self.logger.info(f"  Got {len(items)} items from {endpoint}")
                        return items
                    else:
                        self.logger.info(f"  Parsed 0 items from {endpoint}")
                else:
                    self.logger.info(f"  Non-200 response, skipping")
            except requests.RequestException as e:
                self.logger.warning(f"  Request failed: {e}")
            except ValueError as e:
                self.logger.warning(f"  JSON parse failed: {e}")
        return []

    def _scrape_from_projects(self) -> list[dict]:
        """Fetch projects and extract commercial/office type listings."""
        items = []

        try:
            self.logger.info(f"Fetching projects from {PROJECTS_URL}")
            resp = self.session.get(PROJECTS_URL, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch projects: {e}")
            return []
        except ValueError as e:
            self.logger.error(f"Failed to parse projects JSON: {e}")
            return []

        # Extract the projects list
        projects = []
        if isinstance(data, dict):
            projects = data.get("data", data.get("results", data.get("items", [])))
            self.logger.info(f"Projects response keys: {list(data.keys())}")
        elif isinstance(data, list):
            projects = data

        self.logger.info(f"Found {len(projects)} projects")

        for project in projects:
            if not isinstance(project, dict):
                continue

            project_id = project.get("id", "")
            project_name = project.get("name", project.get("title", ""))
            project_uuid = project.get("uuid", "")
            project_slug = project.get("slug", "")
            self.logger.info(f"Processing project: {project_name} (id={project_id})")

            # Look for flats/offices within the project response
            flats = project.get("flats", [])
            if isinstance(flats, list):
                for flat_group in flats:
                    if not isinstance(flat_group, dict):
                        continue
                    flat_type = flat_group.get("type", "")
                    self.logger.info(f"  Flat group type='{flat_type}', "
                                     f"min_cost={flat_group.get('min_cost')}, "
                                     f"max_cost={flat_group.get('max_cost')}")

                    # Include non-apartment types (office, commercial, etc.)
                    if flat_type and flat_type != "apartment":
                        parsed_items = self._parse_flat_group(flat_group, project)
                        items.extend(parsed_items)

            # Also try fetching project-specific commercial endpoint
            if project_id:
                project_items = self._fetch_project_commercial(project_id, project)
                items.extend(project_items)

        return items

    def _fetch_project_commercial(self, project_id, project: dict) -> list[dict]:
        """Try to fetch commercial listings for a specific project."""
        endpoints = [
            f"{API_BASE}/building-objects/{project_id}/offices",
            f"{API_BASE}/building-objects/{project_id}/commercial",
            f"{API_BASE}/building-objects/{project_id}/flats?type=office",
            f"{API_BASE}/building-objects/{project_id}/flats?type=commercial",
            f"{API_BASE}/building-objects/projects/{project_id}/offices",
            f"{API_BASE}/building-objects/projects/{project_id}/flats?type=office",
        ]

        for endpoint in endpoints:
            try:
                resp = self.session.get(endpoint, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    self.logger.info(f"  Project endpoint {endpoint}: status=200, "
                                     f"type={type(data).__name__}")
                    items = self._parse_list_response(data, project_context=project)
                    if items:
                        self.logger.info(f"  Got {len(items)} items from {endpoint}")
                        return items
            except Exception as e:
                self.logger.debug(f"  Failed {endpoint}: {e}")

        return []

    def _parse_list_response(self, data, project_context: dict | None) -> list[dict]:
        """Parse a list/paginated API response into property items."""
        raw_items = []
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            for key in ("data", "results", "items", "objects", "offices", "flats", "commercial"):
                if key in data and isinstance(data[key], list):
                    raw_items = data[key]
                    break

        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            # Skip apartments unless explicitly office/commercial
            item_type = raw.get("type", raw.get("flat_type", ""))
            if item_type == "apartment":
                continue
            parsed = self._parse_item(raw, project_context)
            if parsed:
                items.append(parsed)
        return items

    def _parse_flat_group(self, flat_group: dict, project: dict) -> list[dict]:
        """Parse a flat group summary into one or more property items.

        The projects endpoint returns aggregated data (min_cost, max_cost, min_area, max_area)
        rather than individual listings. We create a summary item per group.
        """
        project_id = project.get("id", "")
        project_name = project.get("name", project.get("title", ""))
        flat_type = flat_group.get("type", "commercial")

        # If group_room_count is available, create items per room type
        room_counts = flat_group.get("group_room_count", [])

        items = []
        if room_counts:
            for room in room_counts:
                if not isinstance(room, dict):
                    continue
                room_count = room.get("room_count", room.get("count", ""))
                min_cost = room.get("min_cost") or flat_group.get("min_cost")
                max_cost = room.get("max_cost") or flat_group.get("max_cost")
                min_area = room.get("min_area") or flat_group.get("min_area")
                max_area = room.get("max_area") or flat_group.get("max_area")

                external_id = f"{project_id}_{flat_type}_{room_count}"

                price_value = None
                price_str = "по запросу"
                if min_cost:
                    try:
                        price_value = int(float(str(min_cost).replace(" ", "")))
                        price_str = f"от {price_value}"
                    except (ValueError, TypeError):
                        pass

                area = None
                if min_area:
                    try:
                        area = float(str(min_area).replace(",", ".").replace(" ", ""))
                    except (ValueError, TypeError):
                        pass

                price_per_sqm = None
                if price_value and area and area > 0:
                    price_per_sqm = int(price_value / area)

                items.append({
                    "external_id": external_id,
                    "project_name": project_name,
                    "project_url": f"{SITE_BASE}/emotion/offices",
                    "title": f"{flat_type} (от {min_area} м2)" if min_area else flat_type,
                    "property_url": f"{SITE_BASE}/emotion/offices",
                    "property_type": self._translate_type(flat_type),
                    "status": "в продаже",
                    "address": "",
                    "area": area,
                    "price": price_str,
                    "price_value": price_value,
                    "price_per_sqm": price_per_sqm,
                    "floor": None,
                    "floor_total": None,
                    "completion_date": "",
                    "image_url": "",
                    "images": [],
                    "raw_data": {"flat_group": flat_group, "project": project_name},
                })
        else:
            # Single summary item for the group
            min_cost = flat_group.get("min_cost")
            min_area = flat_group.get("min_area")
            external_id = f"{project_id}_{flat_type}"

            price_value = None
            price_str = "по запросу"
            if min_cost:
                try:
                    price_value = int(float(str(min_cost).replace(" ", "")))
                    price_str = f"от {price_value}"
                except (ValueError, TypeError):
                    pass

            area = None
            if min_area:
                try:
                    area = float(str(min_area).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    pass

            price_per_sqm = None
            if price_value and area and area > 0:
                price_per_sqm = int(price_value / area)

            items.append({
                "external_id": external_id,
                "project_name": project_name,
                "project_url": f"{SITE_BASE}/emotion/offices",
                "title": f"{flat_type} (от {min_area} м2)" if min_area else flat_type,
                "property_url": f"{SITE_BASE}/emotion/offices",
                "property_type": self._translate_type(flat_type),
                "status": "в продаже",
                "address": "",
                "area": area,
                "price": price_str,
                "price_value": price_value,
                "price_per_sqm": price_per_sqm,
                "floor": None,
                "floor_total": None,
                "completion_date": "",
                "image_url": "",
                "images": [],
                "raw_data": {"flat_group": flat_group, "project": project_name},
            })

        return items

    def _parse_item(self, raw: dict, project_context: dict | None) -> dict | None:
        """Parse a single commercial property from API response."""
        external_id = (
            raw.get("id")
            or raw.get("uuid")
            or raw.get("external_id")
            or raw.get("pk")
            or ""
        )
        if not external_id:
            return None

        external_id = str(external_id)

        # Price
        price_value = raw.get("price") or raw.get("cost") or raw.get("total_cost") or raw.get("min_cost")
        if price_value is not None:
            try:
                price_value = int(float(str(price_value).replace(" ", "").replace(",", ".")))
                price_str = str(price_value)
            except (ValueError, TypeError):
                price_value = None
                price_str = "по запросу"
        else:
            price_str = "по запросу"

        # Area
        area = raw.get("area") or raw.get("total_area") or raw.get("area_total") or raw.get("min_area")
        if area is not None:
            try:
                area = float(str(area).replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                area = None

        # Price per sqm
        price_per_sqm = raw.get("price_per_sqm") or raw.get("price_per_meter") or raw.get("meter_price")
        if price_per_sqm is not None:
            try:
                price_per_sqm = int(float(str(price_per_sqm).replace(" ", "").replace(",", ".")))
            except (ValueError, TypeError):
                price_per_sqm = None
        elif price_value and area and area > 0:
            price_per_sqm = int(price_value / area)

        # Floor
        floor = raw.get("floor") or raw.get("floor_number")
        if floor is not None:
            try:
                floor = int(floor)
            except (ValueError, TypeError):
                floor = None

        # Floor total
        floor_total = raw.get("floor_total") or raw.get("floors_count") or raw.get("total_floors")
        if floor_total is not None:
            try:
                floor_total = int(floor_total)
            except (ValueError, TypeError):
                floor_total = None

        # Project info
        project_name = ""
        project_url = ""
        if project_context and isinstance(project_context, dict):
            project_name = project_context.get("name", project_context.get("title", ""))
            project_slug = project_context.get("slug", "")
            if project_slug:
                project_url = f"{SITE_BASE}/{project_slug}/offices"
        if not project_name:
            project_name = raw.get("project_name") or raw.get("complex_name") or ""
            if isinstance(raw.get("project"), dict):
                project_name = raw["project"].get("name", project_name)
            elif isinstance(raw.get("building_object"), dict):
                project_name = raw["building_object"].get("name", project_name)

        # Completion date
        completion_date = (
            raw.get("completion_date")
            or raw.get("delivery_date")
            or raw.get("deadline")
            or raw.get("commissioning_date")
            or ""
        )
        if isinstance(completion_date, str) and completion_date:
            completion_date = self._format_completion_date(completion_date)

        # Title
        number = raw.get("number") or raw.get("name") or raw.get("title") or ""
        if number and not str(number).startswith("Помещение"):
            title = f"Помещение {number}"
        else:
            title = str(number) if number else ""

        # Property type
        property_type = raw.get("type") or raw.get("flat_type") or raw.get("purpose") or "коммерческое"
        property_type = self._translate_type(property_type)

        # Property URL
        property_url = raw.get("url") or raw.get("link") or ""
        if not property_url:
            property_url = f"{SITE_BASE}/emotion/offices"

        # Image
        image_url = raw.get("image") or raw.get("image_url") or raw.get("photo") or ""
        images = raw.get("images") or raw.get("photos") or raw.get("gallery") or []
        if isinstance(images, list):
            images = [img if isinstance(img, str) else img.get("url", img.get("src", ""))
                      for img in images if img]
        else:
            images = []

        # Status
        status = raw.get("status") or raw.get("sale_status") or "в продаже"

        # Finishing
        finishing = raw.get("finishing") or raw.get("decoration") or ""
        has_finishing = None
        if isinstance(finishing, str) and finishing:
            has_finishing = "без" not in finishing.lower()
        elif isinstance(finishing, (int, bool)):
            has_finishing = bool(finishing)
            finishing = "С отделкой" if has_finishing else "Без отделки"

        # Ceiling height
        ceiling_height = raw.get("ceiling_height") or raw.get("height")
        if ceiling_height is not None:
            try:
                ceiling_height = float(str(ceiling_height).replace(",", "."))
            except (ValueError, TypeError):
                ceiling_height = None

        # Address
        address = raw.get("address") or ""
        if isinstance(raw.get("building_object"), dict):
            address = address or raw["building_object"].get("address", "")

        return {
            "external_id": external_id,
            "project_name": project_name,
            "project_url": project_url,
            "title": title,
            "property_url": property_url,
            "property_type": property_type,
            "status": str(status),
            "address": address,
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "floor": floor,
            "floor_total": floor_total,
            "ceiling_height": ceiling_height,
            "finishing": str(finishing),
            "has_finishing": has_finishing,
            "completion_date": completion_date,
            "image_url": image_url,
            "images": images,
            "raw_data": raw,
        }

    @staticmethod
    def _translate_type(type_str: str) -> str:
        """Translate API type values to Russian labels."""
        type_map = {
            "office": "офис",
            "commercial": "коммерческое",
            "retail": "торговое",
            "apartment": "квартира",
            "storage": "кладовая",
            "parking": "паркинг",
        }
        if isinstance(type_str, str):
            return type_map.get(type_str.lower(), type_str)
        return str(type_str)

    @staticmethod
    def _format_completion_date(date_str: str) -> str:
        """Normalize completion date to readable format like '4 кв 2027'."""
        if re.search(r"\d\s*кв", date_str.lower()):
            return date_str

        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            quarter = (dt.month - 1) // 3 + 1
            return f"{quarter} кв {dt.year}"
        except (ValueError, AttributeError):
            pass

        return date_str


if __name__ == "__main__":
    OsnovaScraper().loop()
