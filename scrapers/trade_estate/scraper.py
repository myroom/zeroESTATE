"""Скрапер коммерческой недвижимости Основа Trade Estate (trade-estate.ru).

Bitrix CMS, server-rendered. No REST API.
Strategy:
  1. Load listing page with project cards
  2. Extract project links and metro info from cards
  3. Navigate to each project detail page
  4. Extract individual lots with price, area, floor
"""

import re
import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class TradeEstateScraper(BrowserScraper):
    slug = "trade_estate"
    name = "Основа Trade Estate"
    base_url = "https://trade-estate.ru/sale/"

    CARD_SELECTOR = ".product__card"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        all_items = []

        # --- Step 1: Load listing page and extract project cards ---
        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(2, 4))

        # Wait for catalog to load (Bitrix renders asynchronously)
        try:
            page.wait_for_function("document.body.innerText.includes('найдено')", timeout=30000)
            self.logger.info("Catalog loaded (found 'найдено' text)")
        except Exception:
            self.logger.warning("Catalog text not found, waiting extra time...")
            time.sleep(10)

        # Scroll to trigger lazy loading
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)

        # Check for anti-bot
        if self._detect_anti_bot(page):
            from scrapers.browser_scraper import _AntiBotDetected
            raise _AntiBotDetected("Anti-bot detected on listing page")

        # Debug: log page info
        debug_info = page.evaluate("() => ({title: document.title, url: location.href, bodyLen: document.body.innerText.length, allLinks: document.querySelectorAll('a[href*=\"/sale/\"]').length})")
        self.logger.info(f"Page: {debug_info}")

        # Extract project card data from listing page
        projects = page.evaluate("""() => {
            const cards = document.querySelectorAll('.product__card');
            const results = [];

            cards.forEach(card => {
                try {
                    // Project link - inside a.product__title or a.product__image
                    const linkEl = card.querySelector('a.product__title') || card.querySelector('a.product__image') || card.querySelector('a[href*="/sale/"]');
                    if (!linkEl) return;
                    const href = linkEl.href || '';
                    if (!href || !href.includes('/sale/')) return;

                    const text = card.innerText || '';
                    if (!text.trim()) return;

                    // Project name: first heading or prominent text
                    const nameEl = card.querySelector('h1, h2, h3, h4, .product__card-title, [class*="title"], [class*="name"]');
                    const projectName = nameEl ? nameEl.innerText.trim() : '';

                    // Metro station + distance
                    // Pattern: "Ростокино 1 мин" or metro icon followed by station name
                    const metroEl = card.querySelector('[class*="metro"], [class*="Metro"], [class*="subway"]');
                    let metroStation = '';
                    let metroDistanceMin = null;
                    if (metroEl) {
                        const metroText = metroEl.innerText.trim();
                        metroStation = metroText;
                        const distMatch = metroText.match(/(\\d+)\\s*мин/);
                        if (distMatch) {
                            metroDistanceMin = parseInt(distMatch[1]);
                            // Station name is everything before the distance
                            metroStation = metroText.replace(/\\d+\\s*мин\\.?/, '').trim();
                        }
                    }
                    // Fallback: extract metro from full text
                    if (!metroStation) {
                        const metroMatch = text.match(/([А-Яа-яёЁ\\s-]+?)\\s+(\\d+)\\s*мин/);
                        if (metroMatch) {
                            metroStation = metroMatch[1].trim();
                            metroDistanceMin = parseInt(metroMatch[2]);
                        }
                    }

                    // Area range from card: "100.6 - 865.7 м²" or "153.7 м²"
                    const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*(?:-\\s*(\\d+[.,]?\\d*))?\\s*м[²2]/);
                    let areaMin = null;
                    let areaMax = null;
                    if (areaMatch) {
                        areaMin = parseFloat(areaMatch[1].replace(',', '.'));
                        if (areaMatch[2]) {
                            areaMax = parseFloat(areaMatch[2].replace(',', '.'));
                        }
                    }

                    // Number of units: "Продажа: 3 шт"
                    const unitsMatch = text.match(/(\\d+)\\s*шт/);
                    const unitsCount = unitsMatch ? parseInt(unitsMatch[1]) : null;

                    // Image
                    const imgEl = card.querySelector('img');
                    const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';

                    results.push({
                        href: href,
                        project_name: projectName,
                        metro_station: metroStation,
                        metro_distance_min: metroDistanceMin,
                        area_min: areaMin,
                        area_max: areaMax,
                        units_count: unitsCount,
                        image_url: imageUrl,
                        raw_text: text.substring(0, 500),
                    });
                } catch(e) {}
            });
            return results;
        }""")

        self.logger.info(f"Found {len(projects)} project cards on listing page")

        if not projects:
            self.logger.warning("No project cards found, returning empty")
            return []

        # --- Step 2: Visit each project detail page ---
        for proj in projects:
            detail_url = proj.get("href", "")
            if not detail_url:
                continue

            # Ensure ROOM_DEAL param for sale listings
            if "ROOM_DEAL" not in detail_url:
                separator = "&" if "?" in detail_url else "?"
                detail_url += separator + "ROOM_DEAL=%D0%9F%D1%80%D0%BE%D0%B4%D0%B0%D0%B6%D0%B0"

            self.logger.info(f"Navigating to detail: {detail_url}")
            time.sleep(random.uniform(1, 3))

            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(random.uniform(2, 4))

                if self._detect_anti_bot(page):
                    self.logger.warning(f"Anti-bot on detail page {detail_url}, skipping project")
                    continue

                lots = self._extract_lots(page, proj)
                self.logger.info(f"  Extracted {len(lots)} lots from {proj.get('project_name', '?')}")
                all_items.extend(lots)

            except Exception as e:
                self.logger.warning(f"Error loading detail page {detail_url}: {e}")
                continue

        # If no individual lots found, fall back to project-level items
        if not all_items:
            self.logger.info("No individual lots found, creating project-level items")
            all_items = self._fallback_project_items(projects)

        # Deduplicate by external_id
        seen = set()
        deduped = []
        for item in all_items:
            eid = item["external_id"]
            if eid not in seen:
                seen.add(eid)
                deduped.append(item)

        self.logger.info(f"Total items collected: {len(deduped)} (after dedup)")
        return deduped

    def _extract_lots(self, page: Page, project: dict) -> list[dict]:
        """Extract individual lots/units from a project detail page."""
        project_name = project.get("project_name", "")
        project_url = project.get("href", "")
        metro_station = project.get("metro_station", "")
        metro_distance_min = project.get("metro_distance_min")
        project_image = project.get("image_url", "")

        # Extract lots from detail page via JS
        raw_lots = page.evaluate("""() => {
            const lots = [];

            // Strategy 1: Look for table rows with lot data
            const rows = document.querySelectorAll(
                'table tbody tr, '
                + '.product__list-item, '
                + '[class*="lot"], [class*="Lot"], '
                + '[class*="room"], [class*="Room"], '
                + '[class*="unit"], [class*="Unit"], '
                + '[class*="flat"], [class*="Flat"], '
                + '[class*="offer"], [class*="Offer"]'
            );

            rows.forEach(row => {
                try {
                    const text = row.innerText || '';
                    if (text.length < 10) return;

                    // Price: "17 249 650 ₽" or "XX млн ₽" or "от XX"
                    let priceValue = null;
                    let priceStr = 'по запросу';

                    // Try exact price: digits with spaces + currency
                    const exactPriceMatch = text.match(/(\\d[\\d\\s]{2,})\\s*[₽руб\\u20BD]/);
                    if (exactPriceMatch) {
                        const cleaned = exactPriceMatch[1].replace(/\\s/g, '');
                        priceValue = parseInt(cleaned);
                        if (priceValue > 0) {
                            priceStr = String(priceValue);
                        } else {
                            priceValue = null;
                        }
                    }
                    // Try "XX.X млн"
                    if (!priceValue) {
                        const mlnMatch = text.match(/(\\d+[.,]?\\d*)\\s*млн/);
                        if (mlnMatch) {
                            priceValue = Math.round(parseFloat(mlnMatch[1].replace(',', '.')) * 1000000);
                            priceStr = mlnMatch[0].trim();
                        }
                    }
                    if (/по\\s*запросу/i.test(text)) {
                        priceStr = 'по запросу';
                        priceValue = null;
                    }

                    // Area: "100.6 м²"
                    const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                    // Floor: "этаж X" or "X этаж" or just a number in floor column
                    let floor = null;
                    const floorMatch = text.match(/(?:этаж|эт\\.?)\\s*(\\d+)/i)
                                    || text.match(/(\\d+)\\s*(?:этаж|эт\\.?)/i);
                    if (floorMatch) {
                        floor = parseInt(floorMatch[1]);
                    }

                    // Type: офис, ПСН, торговое, ритейл
                    let propertyType = '';
                    const textLower = text.toLowerCase();
                    if (textLower.includes('офис')) propertyType = 'офис';
                    else if (textLower.includes('псн')) propertyType = 'ПСН';
                    else if (textLower.includes('торгов') || textLower.includes('ритейл') || textLower.includes('стрит'))
                        propertyType = 'торговое';
                    else if (textLower.includes('свобод')) propertyType = 'свободное назначение';
                    else if (textLower.includes('склад')) propertyType = 'склад';

                    // Lot link
                    const linkEl = row.querySelector('a[href]');
                    const lotUrl = linkEl ? linkEl.href : '';

                    // Lot number or ID
                    const numMatch = text.match(/[№#]\\s*(\\d+)/);
                    const lotNum = numMatch ? numMatch[1] : '';

                    // Image
                    const imgEl = row.querySelector('img');
                    const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';

                    // Only keep rows that have at least price or area
                    if (area || priceValue) {
                        lots.push({
                            price_value: priceValue,
                            price_str: priceStr,
                            area: area,
                            floor: floor,
                            property_type: propertyType,
                            lot_url: lotUrl,
                            lot_num: lotNum,
                            image_url: imageUrl,
                            raw_text: text.substring(0, 400),
                        });
                    }
                } catch(e) {}
            });

            // Strategy 2: If no structured lots found, try parsing the entire page text
            // for price/area blocks (some Bitrix sites show data in custom divs)
            if (lots.length === 0) {
                const allBlocks = document.querySelectorAll(
                    '.product__detail-item, '
                    + '[class*="card"], '
                    + '[class*="object-item"], '
                    + '[class*="property-item"]'
                );
                allBlocks.forEach(block => {
                    try {
                        const text = block.innerText || '';
                        if (text.length < 10) return;

                        let priceValue = null;
                        let priceStr = 'по запросу';
                        const exactPriceMatch = text.match(/(\\d[\\d\\s]{2,})\\s*[₽руб\\u20BD]/);
                        if (exactPriceMatch) {
                            const cleaned = exactPriceMatch[1].replace(/\\s/g, '');
                            priceValue = parseInt(cleaned);
                            if (priceValue > 0) priceStr = String(priceValue);
                            else priceValue = null;
                        }
                        if (!priceValue) {
                            const mlnMatch = text.match(/(\\d+[.,]?\\d*)\\s*млн/);
                            if (mlnMatch) {
                                priceValue = Math.round(parseFloat(mlnMatch[1].replace(',', '.')) * 1000000);
                                priceStr = mlnMatch[0].trim();
                            }
                        }

                        const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                        const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                        let floor = null;
                        const floorMatch = text.match(/(?:этаж|эт\\.?)\\s*(\\d+)/i)
                                        || text.match(/(\\d+)\\s*(?:этаж|эт\\.?)/i);
                        if (floorMatch) floor = parseInt(floorMatch[1]);

                        const linkEl = block.querySelector('a[href]');
                        const lotUrl = linkEl ? linkEl.href : '';

                        if (area || priceValue) {
                            lots.push({
                                price_value: priceValue,
                                price_str: priceStr,
                                area: area,
                                floor: floor,
                                property_type: '',
                                lot_url: lotUrl,
                                lot_num: '',
                                image_url: '',
                                raw_text: text.substring(0, 400),
                            });
                        }
                    } catch(e) {}
                });
            }

            return lots;
        }""")

        items = []
        for lot in raw_lots:
            try:
                area = lot.get("area")
                price_value = lot.get("price_value")
                floor = lot.get("floor")
                lot_url = lot.get("lot_url", "")

                # Build external_id from lot URL or compose from project + area + floor
                external_id = ""
                if lot_url:
                    # Try to extract ID from URL params or path
                    id_match = re.search(r'[?&](?:id|ID|ELEMENT_ID)=(\d+)', lot_url)
                    if id_match:
                        external_id = f"te-{id_match.group(1)}"
                    else:
                        # Use URL slug
                        slug_match = re.search(r'/sale/([^/?#]+)', lot_url)
                        if slug_match:
                            slug = slug_match.group(1).rstrip('/')
                            external_id = f"te-{slug}"

                if not external_id:
                    # Compose from project slug + area + floor
                    proj_slug = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ]', '-', project_name.lower())[:30]
                    area_str = f"{area:.1f}" if area else "0"
                    floor_str = str(floor) if floor else "0"
                    external_id = f"te-{proj_slug}-{area_str}-{floor_str}"

                # Determine property type
                property_type = lot.get("property_type", "")
                if not property_type:
                    property_type = self._guess_property_type(project_name)

                # Price per sqm
                price_per_sqm = None
                if price_value and area and area > 0:
                    price_per_sqm = int(price_value / area)

                items.append({
                    "external_id": external_id,
                    "project_name": project_name,
                    "project_url": project_url,
                    "title": f"{project_name} - {area or '?'} м²" + (f", этаж {floor}" if floor else ""),
                    "property_url": lot_url or project_url,
                    "property_type": property_type or "коммерческое",
                    "status": "в продаже",
                    "metro_station": metro_station,
                    "metro_distance_min": metro_distance_min,
                    "area": area,
                    "price": lot.get("price_str", "по запросу"),
                    "price_value": price_value,
                    "price_per_sqm": price_per_sqm,
                    "floor": floor,
                    "image_url": lot.get("image_url", "") or project_image,
                    "raw_data": {
                        "raw_text": lot.get("raw_text", ""),
                        "lot_num": lot.get("lot_num", ""),
                        "source_project": project.get("raw_text", "")[:200],
                    },
                })
            except Exception as e:
                self.logger.warning(f"Error processing lot: {e}")
                continue

        return items

    def _fallback_project_items(self, projects: list[dict]) -> list[dict]:
        """Create project-level items when individual lots cannot be extracted."""
        items = []
        for proj in projects:
            project_name = proj.get("project_name", "")
            href = proj.get("href", "")

            # Use project slug as external ID
            slug_match = re.search(r'/sale/([^/?#]+)', href)
            slug = slug_match.group(1).rstrip('/') if slug_match else ""
            if not slug:
                slug = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ]', '-', project_name.lower())[:40]
            external_id = f"te-proj-{slug}"

            area = proj.get("area_min")
            property_type = self._guess_property_type(project_name)

            items.append({
                "external_id": external_id,
                "project_name": project_name,
                "project_url": href,
                "title": project_name,
                "property_url": href,
                "property_type": property_type or "коммерческое",
                "status": "в продаже",
                "metro_station": proj.get("metro_station", ""),
                "metro_distance_min": proj.get("metro_distance_min"),
                "area": area,
                "price": "по запросу",
                "price_value": None,
                "image_url": proj.get("image_url", ""),
                "raw_data": {
                    "raw_text": proj.get("raw_text", ""),
                    "area_min": proj.get("area_min"),
                    "area_max": proj.get("area_max"),
                    "units_count": proj.get("units_count"),
                },
            })

        return items

    @staticmethod
    def _guess_property_type(name: str) -> str:
        """Guess property type from project name."""
        lower = name.lower()
        if "стрит" in lower or "ритейл" in lower or "retail" in lower or "торгов" in lower:
            return "торговое"
        if "офис" in lower or "office" in lower:
            return "офис"
        if "псн" in lower:
            return "ПСН"
        if "склад" in lower:
            return "склад"
        if "мфк" in lower:
            return "коммерческое"
        return ""


if __name__ == "__main__":
    TradeEstateScraper().loop()
