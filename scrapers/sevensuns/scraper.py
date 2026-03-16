"""Скрапер коммерческой недвижимости Seven Suns (Playwright, server-rendered Bitrix)."""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper, _AntiBotDetected
from playwright.sync_api import Browser, Page

# Known project pages with metro info
PROJECTS = [
    {
        "url": "https://sevensuns.ru/commercial-projects/station-l/",
        "name": "Station L",
        "metro": "Братиславская",
        "metro_distance_min": 20,
    },
    {
        "url": "https://sevensuns.ru/commercial-projects/skazochniyles/",
        "name": "Сказочный лес",
        "metro": "Ростокино",
        "metro_distance_min": 10,
    },
    {
        "url": "https://sevensuns.ru/commercial-projects/v-stremlenii-k-svety/",
        "name": "В стремлении к свету",
        "metro": "Алтуфьево",
        "metro_distance_min": 10,
    },
]

# Unified listing page
COMMERCIAL_PAGE = "https://sevensuns.ru/commercial/"


class SevenSunsScraper(BrowserScraper):
    slug = "sevensuns"
    name = "Seven Suns"
    base_url = "https://sevensuns.ru/commercial-projects/"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        items = []

        # Strategy 1: Try the unified /commercial/ listing page first
        unified_items = self._scrape_unified_page(page)
        if unified_items:
            self.logger.info(f"Unified page yielded {len(unified_items)} items")
            items.extend(unified_items)

        # Strategy 2: Scrape individual project pages for additional data
        project_items = self._scrape_project_pages(page)
        if project_items:
            self.logger.info(f"Project pages yielded {len(project_items)} items")
            # Merge: add items from project pages that are not already in unified
            existing_ids = {item["external_id"] for item in items}
            for item in project_items:
                if item["external_id"] not in existing_ids:
                    items.append(item)
                    existing_ids.add(item["external_id"])
                else:
                    # Enrich existing items with project-specific data
                    self._enrich_item(items, item)

        self.logger.info(f"Total items collected: {len(items)}")
        return items

    # ------------------------------------------------------------------
    # Unified listing page
    # ------------------------------------------------------------------

    def _scrape_unified_page(self, page: Page) -> list[dict]:
        """Scrape the unified /commercial/ page."""
        items = []
        try:
            self.logger.info(f"Loading unified page: {COMMERCIAL_PAGE}")
            page.goto(COMMERCIAL_PAGE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            if self._detect_anti_bot(page):
                raise _AntiBotDetected("Anti-bot detected on unified page")

            # Try to find commercial unit cards/rows
            items = self._extract_units_from_page(page, project_info=None)

        except _AntiBotDetected:
            raise
        except Exception as e:
            self.logger.warning(f"Failed to scrape unified page: {e}")

        return items

    # ------------------------------------------------------------------
    # Individual project pages
    # ------------------------------------------------------------------

    def _scrape_project_pages(self, page: Page) -> list[dict]:
        """Scrape each known project page."""
        all_items = []

        for project in PROJECTS:
            try:
                self.logger.info(f"Loading project: {project['name']} -> {project['url']}")
                page.goto(project["url"], wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                if self._detect_anti_bot(page):
                    raise _AntiBotDetected(f"Anti-bot detected on {project['url']}")

                items = self._extract_units_from_page(page, project_info=project)
                self.logger.info(f"  -> {len(items)} units from {project['name']}")
                all_items.extend(items)

            except _AntiBotDetected:
                raise
            except Exception as e:
                self.logger.warning(f"Failed to scrape {project['name']}: {e}")

        return all_items

    # ------------------------------------------------------------------
    # Unit extraction
    # ------------------------------------------------------------------

    def _extract_units_from_page(self, page: Page, project_info: dict | None) -> list[dict]:
        """Extract commercial units from the current page using multiple strategies."""
        items = []

        # Strategy A: Look for structured unit cards/rows via common CSS patterns
        items = self._extract_via_selectors(page, project_info)
        if items:
            return items

        # Strategy B: Extract from tables (common in Bitrix sites)
        items = self._extract_from_tables(page, project_info)
        if items:
            return items

        # Strategy C: Parse all text blocks with area/price patterns
        items = self._extract_from_text_blocks(page, project_info)
        return items

    def _extract_via_selectors(self, page: Page, project_info: dict | None) -> list[dict]:
        """Try common card/listing selectors for commercial units."""
        items = []
        # Common selectors for commercial unit cards on Bitrix sites
        selectors = [
            ".commercial-card",
            ".commercial-item",
            ".commercial__item",
            ".commercial-list__item",
            ".object-card",
            ".flat-card",
            ".unit-card",
            "[data-type='commercial']",
            ".catalog-item",
            ".catalog__item",
            ".js-commercial-item",
            ".property-card",
            ".offer-card",
            ".spaces__item",
            ".spaces-item",
        ]

        for selector in selectors:
            try:
                cards = page.query_selector_all(selector)
                if not cards:
                    continue
                self.logger.info(f"Found {len(cards)} cards with selector '{selector}'")
                for idx, card in enumerate(cards):
                    item = self._parse_card(card, idx, project_info, page.url)
                    if item:
                        items.append(item)
                if items:
                    return items
            except Exception:
                continue

        return items

    def _extract_from_tables(self, page: Page, project_info: dict | None) -> list[dict]:
        """Extract units from HTML tables."""
        items = []
        try:
            tables = page.query_selector_all("table")
            for table in tables:
                rows = table.query_selector_all("tr")
                if len(rows) < 2:
                    continue

                # Try to detect header row
                header_row = rows[0]
                headers = [
                    (th.inner_text() or "").strip().lower()
                    for th in header_row.query_selector_all("th, td")
                ]
                if not headers:
                    continue

                # Check if this looks like a commercial units table
                has_area = any("площ" in h or "м²" in h or "м2" in h for h in headers)
                has_price = any("цен" in h or "стоим" in h or "руб" in h for h in headers)
                if not (has_area or has_price):
                    continue

                self.logger.info(f"Found table with headers: {headers}")

                # Map column indices
                col_map = self._map_table_columns(headers)

                for row_idx, row in enumerate(rows[1:], start=1):
                    cells = [
                        (td.inner_text() or "").strip()
                        for td in row.query_selector_all("td")
                    ]
                    if not cells or all(not c for c in cells):
                        continue

                    item = self._parse_table_row(cells, col_map, row_idx, project_info, page.url)
                    if item:
                        items.append(item)

        except Exception as e:
            self.logger.warning(f"Table extraction failed: {e}")

        return items

    def _extract_from_text_blocks(self, page: Page, project_info: dict | None) -> list[dict]:
        """Last resort: scan page for text blocks containing area/price data."""
        items = []
        try:
            content = page.content()
            # Look for patterns like "123.4 м²" combined with price
            pattern = re.compile(
                r"(\d+[.,]?\d*)\s*(?:м²|м2|кв\.?\s*м)"
                r".*?"
                r"(\d[\d\s.,]*)\s*(?:руб|₽|р\.)",
                re.IGNORECASE | re.DOTALL,
            )

            # Also try link-based extraction
            links = page.query_selector_all("a[href*='commercial'], a[href*='office'], a[href*='помещен']")
            for idx, link in enumerate(links):
                text = (link.inner_text() or "").strip()
                href = link.get_attribute("href") or ""
                if not text:
                    continue

                area = self._extract_area_from_text(text)
                price_str, price_value = self._extract_price_from_text(text)

                if area or price_value:
                    external_id = href or f"unit-{idx}"
                    external_id = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ/_-]", "", external_id)[-200:]
                    if not external_id:
                        external_id = f"text-unit-{idx}"

                    item = self._build_item(
                        external_id=external_id,
                        title=text[:200],
                        area=area,
                        price_str=price_str,
                        price_value=price_value,
                        property_url=self._make_absolute(href),
                        project_info=project_info,
                    )
                    items.append(item)

        except Exception as e:
            self.logger.warning(f"Text block extraction failed: {e}")

        return items

    # ------------------------------------------------------------------
    # Card / row parsing
    # ------------------------------------------------------------------

    def _parse_card(self, card, idx: int, project_info: dict | None, page_url: str) -> dict | None:
        """Parse a single unit card element."""
        try:
            text = (card.inner_text() or "").strip()
            if not text:
                return None

            # Try to find a link
            link = card.query_selector("a")
            href = ""
            if link:
                href = link.get_attribute("href") or ""

            # External ID from data attributes or href
            external_id = (
                card.get_attribute("data-id")
                or card.get_attribute("data-flat-id")
                or card.get_attribute("id")
                or href
                or f"card-{idx}"
            )

            # Title
            title_el = card.query_selector(
                ".title, .name, h3, h4, .commercial-card__title, .object-card__title"
            )
            title = (title_el.inner_text() if title_el else "").strip() or text[:100]

            # Area
            area = self._extract_area_from_text(text)

            # Price
            price_str, price_value = self._extract_price_from_text(text)

            # Floor
            floor = self._extract_floor_from_text(text)

            if not area and not price_value:
                return None

            return self._build_item(
                external_id=str(external_id),
                title=title,
                area=area,
                price_str=price_str,
                price_value=price_value,
                floor=floor,
                property_url=self._make_absolute(href),
                project_info=project_info,
            )

        except Exception as e:
            self.logger.warning(f"Failed to parse card {idx}: {e}")
            return None

    def _map_table_columns(self, headers: list[str]) -> dict:
        """Map column indices by header text."""
        col_map = {}
        for i, h in enumerate(headers):
            if "номер" in h or "помещ" in h or "назван" in h or "лот" in h:
                col_map["title"] = i
            elif "площ" in h or "м²" in h or "м2" in h:
                col_map["area"] = i
            elif "цен" in h or "стоим" in h or "руб" in h:
                col_map["price"] = i
            elif "этаж" in h:
                col_map["floor"] = i
            elif "тип" in h or "назначен" in h:
                col_map["type"] = i
            elif "статус" in h:
                col_map["status"] = i
            elif "срок" in h or "сдач" in h or "дат" in h:
                col_map["completion"] = i
        return col_map

    def _parse_table_row(
        self,
        cells: list[str],
        col_map: dict,
        row_idx: int,
        project_info: dict | None,
        page_url: str,
    ) -> dict | None:
        """Parse a single table row into a property item."""
        title = self._get_cell(cells, col_map.get("title")) or f"Помещение {row_idx}"
        area_text = self._get_cell(cells, col_map.get("area")) or ""
        price_text = self._get_cell(cells, col_map.get("price")) or ""
        floor_text = self._get_cell(cells, col_map.get("floor")) or ""
        type_text = self._get_cell(cells, col_map.get("type")) or ""
        status_text = self._get_cell(cells, col_map.get("status")) or ""
        completion_text = self._get_cell(cells, col_map.get("completion")) or ""

        area = self._extract_area_from_text(area_text) or self._parse_float(area_text)
        price_str, price_value = self._extract_price_from_text(price_text)
        floor = self._extract_floor_from_text(floor_text) or self._parse_int(floor_text)

        if not area and not price_value and not title:
            return None

        external_id = f"{page_url}-row-{row_idx}"
        if project_info:
            slug = project_info["url"].rstrip("/").split("/")[-1]
            external_id = f"{slug}-{row_idx}"

        item = self._build_item(
            external_id=external_id,
            title=title,
            area=area,
            price_str=price_str,
            price_value=price_value,
            floor=floor,
            property_url=page_url,
            project_info=project_info,
        )
        if type_text:
            item["property_type"] = type_text
        if status_text:
            item["status"] = status_text
        if completion_text:
            item["completion_date"] = completion_text

        return item

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_item(
        self,
        external_id: str,
        title: str,
        area: float | None,
        price_str: str,
        price_value: int | None,
        project_info: dict | None,
        property_url: str = "",
        floor: int | None = None,
    ) -> dict:
        """Build a PropertySnapshot-compatible dict."""
        price_per_sqm = None
        if price_value and area and area > 0:
            price_per_sqm = int(price_value / area)

        project_name = ""
        project_url = ""
        metro_station = ""
        metro_distance_min = None

        if project_info:
            project_name = project_info.get("name", "")
            project_url = project_info.get("url", "")
            metro_station = project_info.get("metro", "")
            metro_distance_min = project_info.get("metro_distance_min")

        return {
            "external_id": external_id,
            "project_name": project_name,
            "project_url": project_url,
            "title": title,
            "property_url": property_url,
            "property_type": "коммерческое",
            "status": "",
            "address": "",
            "metro_station": metro_station,
            "metro_distance_min": metro_distance_min,
            "area": area,
            "price": price_str,
            "price_value": price_value,
            "price_per_sqm": price_per_sqm,
            "floor": floor,
            "completion_date": "",
            "image_url": "",
            "images": [],
            "raw_data": {},
        }

    def _enrich_item(self, items: list[dict], new_item: dict):
        """Enrich an existing item with data from new_item."""
        for item in items:
            if item["external_id"] == new_item["external_id"]:
                # Fill empty fields
                for key in ("metro_station", "metro_distance_min", "project_name",
                            "project_url", "address", "completion_date", "floor",
                            "property_type", "status"):
                    if not item.get(key) and new_item.get(key):
                        item[key] = new_item[key]
                break

    @staticmethod
    def _extract_area_from_text(text: str) -> float | None:
        """Extract area in m2 from text."""
        match = re.search(r"(\d+[.,]?\d*)\s*(?:м²|м2|кв\.?\s*м)", text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
        # Just a bare number that could be area (between 10 and 10000)
        return None

    @staticmethod
    def _extract_price_from_text(text: str) -> tuple[str, int | None]:
        """Extract price from text."""
        if not text:
            return "по запросу", None
        if "запрос" in text.lower():
            return "по запросу", None

        # Match price patterns: digits with possible spaces/dots as thousands separators
        # followed by optional currency markers
        match = re.search(
            r"(\d[\d\s\xa0.,]*\d)\s*(?:руб|₽|р\.|млн|тыс)?",
            text, re.IGNORECASE
        )
        if match:
            raw = match.group(1)
            # Clean separators
            cleaned = re.sub(r"[\s\xa0.,]", "", raw)
            try:
                value = int(cleaned)
                if value > 0:
                    return str(value), value
            except ValueError:
                pass

        return "по запросу", None

    @staticmethod
    def _extract_floor_from_text(text: str) -> int | None:
        """Extract floor number from text."""
        match = re.search(r"(\d+)\s*(?:этаж|эт\.)", text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None

    @staticmethod
    def _make_absolute(url: str) -> str:
        if not url:
            return ""
        if url.startswith("http"):
            return url
        return f"https://sevensuns.ru{url}"

    @staticmethod
    def _get_cell(cells: list[str], idx: int | None) -> str | None:
        if idx is None or idx >= len(cells):
            return None
        return cells[idx]

    @staticmethod
    def _parse_float(val) -> float | None:
        if not val:
            return None
        try:
            cleaned = re.sub(r"[^\d.,]", "", str(val)).replace(",", ".")
            f = float(cleaned)
            return f if f > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_int(val) -> int | None:
        if not val:
            return None
        try:
            cleaned = re.sub(r"[^\d]", "", str(val))
            i = int(cleaned)
            return i if i > 0 else None
        except (ValueError, TypeError):
            return None


if __name__ == "__main__":
    SevenSunsScraper().loop()
