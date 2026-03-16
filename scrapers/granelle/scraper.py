"""Скрапер коммерческой недвижимости Гранель (REST API + JSON-LD fallback)."""

import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper

# API endpoints to try for commercial unit listings
PROJECTS_API = "https://granelle.ru/api/projects/?is_released=0"
DETAIL_ENDPOINTS = [
    "https://granelle.ru/api/projects/{slug}/flats/",
    "https://granelle.ru/api/offices/?project={slug}",
    "https://granelle.ru/api/commercial/?project={slug}",
    "https://granelle.ru/api/projects/{slug}/commercial/",
    "https://granelle.ru/api/projects/{slug}/offices/",
]

COMMERCIAL_PAGE = "https://granelle.ru/commercial"
TIMEOUT = 30

HEADERS = {
    "Accept": "application/json, text/html",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://granelle.ru/commercial",
}

# Categories that indicate commercial properties
COMMERCIAL_CATEGORIES = {"business", "commercial", "office", "retail", "trade"}


class GranelleScraper(BaseScraper):
    slug = "granelle"
    name = "Гранель"
    base_url = "https://granelle.ru/commercial"

    def scrape(self) -> list[dict]:
        session = requests.Session()
        session.headers.update(HEADERS)

        # Step 1: Fetch projects list from API
        projects = self._fetch_projects(session)
        commercial_projects = self._filter_commercial(projects)
        self.logger.info(
            f"Found {len(projects)} total projects, "
            f"{len(commercial_projects)} commercial"
        )

        # Step 2: For each commercial project, try to fetch unit details
        items = []
        for project in commercial_projects:
            project_items = self._fetch_project_units(session, project)
            items.extend(project_items)

        self.logger.info(f"Collected {len(items)} items from API")

        # Step 3: If API yielded nothing, fall back to JSON-LD on the page
        if not items:
            self.logger.info("API returned no items, trying JSON-LD fallback")
            items = self._scrape_jsonld(session)
            self.logger.info(f"Collected {len(items)} items from JSON-LD")

        self.logger.info(f"Total items collected: {len(items)}")
        return items

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    def _fetch_projects(self, session: requests.Session) -> list[dict]:
        """Fetch all projects from the Granelle API."""
        try:
            resp = session.get(PROJECTS_API, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("results", data.get("items", data.get("projects", [])))
            return []
        except Exception as e:
            self.logger.warning(f"Failed to fetch projects list: {e}")
            return []

    def _filter_commercial(self, projects: list[dict]) -> list[dict]:
        """Filter for commercial/business projects."""
        result = []
        for p in projects:
            category = (p.get("category") or "").lower().strip()
            tags = [t.lower() for t in (p.get("tags") or [])] if isinstance(p.get("tags"), list) else []
            is_commercial = (
                category in COMMERCIAL_CATEGORIES
                or any(t in COMMERCIAL_CATEGORIES for t in tags)
                or "коммерч" in (p.get("name") or "").lower()
                or "бизнес" in (p.get("name") or "").lower()
            )
            if is_commercial:
                result.append(p)
        # If no commercial filter matched, return all projects (API may already be filtered)
        if not result and projects:
            self.logger.info("No explicit commercial category found; using all projects")
            return projects
        return result

    def _fetch_project_units(self, session: requests.Session, project: dict) -> list[dict]:
        """Try multiple API endpoints to fetch commercial units for a project."""
        slug = project.get("slug", "")
        project_name = project.get("card_title") or project.get("name") or slug
        project_subtitle = project.get("card_subtitle", "")
        if project_subtitle:
            project_name = f"{project_name} {project_subtitle}"

        project_url = f"https://granelle.ru/commercial/{slug}/" if slug else ""

        # Extract project-level images
        project_images = project.get("images", [])
        first_image = ""
        if project_images and isinstance(project_images, list):
            img = project_images[0]
            if isinstance(img, dict):
                first_image = img.get("url") or img.get("src") or img.get("image") or ""
            elif isinstance(img, str):
                first_image = img
        if first_image and not first_image.startswith("http"):
            first_image = f"https://granelle.ru{first_image}"

        items = []
        for endpoint_tpl in DETAIL_ENDPOINTS:
            endpoint = endpoint_tpl.format(slug=slug)
            try:
                self.logger.info(f"Trying endpoint: {endpoint}")
                resp = session.get(endpoint, timeout=TIMEOUT)
                if resp.status_code == 404:
                    self.logger.info(f"  -> 404, skipping")
                    continue
                resp.raise_for_status()
                data = resp.json()

                units = []
                if isinstance(data, list):
                    units = data
                elif isinstance(data, dict):
                    units = (
                        data.get("results")
                        or data.get("items")
                        or data.get("flats")
                        or data.get("offices")
                        or data.get("commercial")
                        or []
                    )

                if not units:
                    self.logger.info(f"  -> 0 units")
                    continue

                self.logger.info(f"  -> {len(units)} units found!")
                for unit in units:
                    mapped = self._map_unit(unit, project_name, project_url, first_image, project)
                    if mapped:
                        items.append(mapped)
                # Found data from this endpoint, no need to try others
                break

            except Exception as e:
                self.logger.info(f"  -> error: {e}")
                continue

        return items

    def _map_unit(
        self,
        unit: dict,
        project_name: str,
        project_url: str,
        project_image: str,
        project_raw: dict,
    ) -> dict | None:
        """Map an API unit to PropertySnapshot fields."""
        external_id = str(
            unit.get("id")
            or unit.get("pk")
            or unit.get("flat_id")
            or unit.get("number")
            or ""
        )
        if not external_id:
            return None

        # Title
        title = (
            unit.get("name")
            or unit.get("title")
            or unit.get("number")
            or f"Помещение {external_id}"
        )
        if isinstance(title, (int, float)):
            title = str(title)

        # Area
        area = self._parse_float(unit.get("area") or unit.get("total_area"))

        # Price
        price_str, price_value = self._extract_price(unit)

        # Price per sqm
        price_per_sqm = None
        if price_value and area and area > 0:
            price_per_sqm = int(price_value / area)
        else:
            raw_ppsm = unit.get("meter_price") or unit.get("price_per_meter") or unit.get("price_sqm")
            if raw_ppsm:
                try:
                    price_per_sqm = int(float(raw_ppsm))
                except (ValueError, TypeError):
                    pass

        # Floor
        floor = self._parse_int(unit.get("floor"))
        floor_total = self._parse_int(unit.get("floor_total") or unit.get("floors"))

        # Ceiling height
        ceiling_height = self._parse_float(unit.get("ceiling_height"))

        # Finishing
        finishing = unit.get("finishing") or unit.get("decoration") or ""
        has_finishing = None
        if finishing:
            has_finishing = True
        elif unit.get("has_finishing") is not None:
            has_finishing = bool(unit.get("has_finishing"))

        # Status
        status = unit.get("status") or unit.get("state") or ""

        # Property type
        property_type = (
            unit.get("type")
            or unit.get("purpose")
            or unit.get("category")
            or "коммерческое"
        )

        # Completion date
        completion_date = unit.get("completion_date") or unit.get("deadline") or ""

        # Images
        unit_images = unit.get("images") or unit.get("photos") or []
        if not isinstance(unit_images, list):
            unit_images = []
        image_urls = []
        for img in unit_images:
            if isinstance(img, dict):
                url = img.get("url") or img.get("src") or img.get("image") or ""
            elif isinstance(img, str):
                url = img
            else:
                continue
            if url:
                if not url.startswith("http"):
                    url = f"https://granelle.ru{url}"
                image_urls.append(url)

        image_url = image_urls[0] if image_urls else project_image

        # Property URL
        property_url = unit.get("url") or unit.get("link") or ""
        if property_url and not property_url.startswith("http"):
            property_url = f"https://granelle.ru{property_url}"

        # Address
        address = unit.get("address") or ""

        # Metro
        metro_station = unit.get("metro") or unit.get("metro_station") or ""
        metro_distance = self._parse_int(unit.get("metro_time") or unit.get("metro_distance_min"))

        # Coordinates
        latitude = self._parse_float(unit.get("latitude") or unit.get("lat"))
        longitude = self._parse_float(unit.get("longitude") or unit.get("lon") or unit.get("lng"))

        raw_data = dict(unit)
        raw_data["_project"] = project_raw

        return {
            "external_id": external_id,
            "project_name": project_name,
            "project_url": project_url,
            "title": str(title),
            "property_url": property_url,
            "property_type": property_type,
            "status": status,
            "address": address,
            "metro_station": metro_station,
            "metro_distance_min": metro_distance,
            "latitude": latitude,
            "longitude": longitude,
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "floor": floor,
            "floor_total": floor_total,
            "ceiling_height": ceiling_height,
            "finishing": finishing,
            "has_finishing": has_finishing,
            "completion_date": completion_date,
            "image_url": image_url,
            "images": image_urls,
            "raw_data": raw_data,
        }

    # ------------------------------------------------------------------
    # JSON-LD fallback
    # ------------------------------------------------------------------

    def _scrape_jsonld(self, session: requests.Session) -> list[dict]:
        """Parse JSON-LD from the commercial page as a fallback."""
        try:
            resp = session.get(COMMERCIAL_PAGE, timeout=TIMEOUT)
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Failed to fetch commercial page: {e}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        items = []

        # Find all JSON-LD script blocks
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            offers = self._extract_offers(data)
            for offer in offers:
                mapped = self._map_jsonld_offer(offer)
                if mapped:
                    items.append(mapped)

        return items

    def _extract_offers(self, data) -> list[dict]:
        """Recursively extract offer objects from JSON-LD data."""
        offers = []
        if isinstance(data, list):
            for item in data:
                offers.extend(self._extract_offers(item))
        elif isinstance(data, dict):
            ld_type = data.get("@type", "")
            if ld_type in ("Offer", "Product", "RealEstateListing", "Apartment", "Place"):
                offers.append(data)
            # Check for nested offers
            if "offers" in data:
                nested = data["offers"]
                if isinstance(nested, list):
                    offers.extend(nested)
                elif isinstance(nested, dict):
                    offers.append(nested)
            # Check for itemListElement
            if "itemListElement" in data:
                for elem in data["itemListElement"]:
                    if isinstance(elem, dict):
                        item = elem.get("item", elem)
                        offers.extend(self._extract_offers(item))
        return offers

    def _map_jsonld_offer(self, offer: dict) -> dict | None:
        """Map a JSON-LD offer to PropertySnapshot fields."""
        name = offer.get("name") or offer.get("description") or ""
        if not name:
            return None

        # Generate external_id from name or URL
        url = offer.get("url") or offer.get("@id") or ""
        external_id = url or name
        # Clean up to make a stable ID
        external_id = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_-]", "_", external_id)[:200]
        if not external_id:
            return None

        # Price
        price_str = "по запросу"
        price_value = None
        price_raw = offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
        if price_raw:
            try:
                pv = int(float(str(price_raw).replace(" ", "").replace("\xa0", "")))
                if pv > 0:
                    price_value = pv
                    price_str = str(pv)
            except (ValueError, TypeError):
                price_str = str(price_raw)

        # Area from description or name
        area = None
        area_match = re.search(r"(\d+[.,]?\d*)\s*(?:м²|м2|кв\.?\s*м)", name)
        if area_match:
            area = float(area_match.group(1).replace(",", "."))

        price_per_sqm = None
        if price_value and area and area > 0:
            price_per_sqm = int(price_value / area)

        # Try to get address from geo
        address = offer.get("address", "")
        if isinstance(address, dict):
            address = address.get("streetAddress") or address.get("name") or ""

        # Image
        image = offer.get("image") or ""
        if isinstance(image, list) and image:
            image = image[0]
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl") or ""

        if url and not url.startswith("http"):
            url = f"https://granelle.ru{url}"
        if image and not image.startswith("http"):
            image = f"https://granelle.ru{image}"

        return {
            "external_id": external_id,
            "project_name": str(name),
            "project_url": url,
            "title": str(name),
            "property_url": url,
            "property_type": "коммерческое",
            "status": "",
            "address": address,
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "image_url": image,
            "images": [image] if image else [],
            "raw_data": offer,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_price(raw: dict) -> tuple[str, int | None]:
        """Extract price string and numeric value."""
        for key in ("price", "price_value", "cost", "total_price"):
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
                digits = re.sub(r"[^\d]", "", cleaned)
                if digits:
                    numeric = int(digits)
                    if numeric > 0:
                        return str(numeric), numeric
        return "по запросу", None

    @staticmethod
    def _parse_float(val) -> float | None:
        if val is None:
            return None
        try:
            f = float(val)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_int(val) -> int | None:
        if val is None:
            return None
        try:
            i = int(float(val))
            return i if i > 0 else None
        except (ValueError, TypeError):
            return None


if __name__ == "__main__":
    GranelleScraper().loop()
