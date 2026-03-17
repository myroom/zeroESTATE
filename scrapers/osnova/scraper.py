"""Скрапер коммерческой недвижимости ГК ОСНОВА (browser-based).

Сайт gk-osnova.ru/emotion/offices — серверный рендеринг, данные в HTML.
API отдаёт только сводку (min/max), а не отдельные помещения.
"""

import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class OsnovaScraper(BrowserScraper):
    slug = "osnova"
    name = "ГК ОСНОВА"
    base_url = "https://gk-osnova.ru/emotion/offices"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(5, 8))

        # Scroll to load content
        for _ in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)

        # Find all links to individual office units
        # Pattern: /emotion/office-premises/... or /emotion/offices/...
        unit_links = page.evaluate("""() => {
            const links = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href;
                if (href.includes('/office-premises/') || href.includes('/offices/')) {
                    // Only unit pages with UUID
                    if (href.match(/[0-9A-F]{8}-[0-9A-F]{4}/i)) {
                        links.add(href);
                    }
                }
            });
            return Array.from(links);
        }""")

        self.logger.info(f"Found {len(unit_links)} unit links")

        # If no direct unit links, try to find them via the listing page
        if len(unit_links) == 0:
            # Try clicking on floor plan / selection buttons
            self.logger.info("No unit links found, trying interactive elements...")

            # Look for "Выбрать" or plan-related elements
            raw = page.evaluate("""() => {
                const text = document.body.innerText;
                // Extract data from text blocks with price/area patterns
                const results = [];
                // Pattern: "Офисное помещение X м²\nY ₽"
                const blocks = text.split(/(?=Офисное помещение|Офис №|№ О\\.)/);
                for (const block of blocks) {
                    if (block.length < 10) continue;
                    const areaMatch = block.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const priceMatch = block.match(/(?:^|\\n)\\s*(\\d[\\d\\s]+)\\s*₽/m);
                    const floorMatch = block.match(/(?:Этаж|этаж)\\s*(\\d+)/i);
                    const numMatch = block.match(/№\\s*([О\\d.]+)/);

                    if (areaMatch || priceMatch) {
                        results.push({
                            text: block.substring(0, 300),
                            area: areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null,
                            price_value: priceMatch ? parseInt(priceMatch[1].replace(/\\s/g, '')) : null,
                            floor: floorMatch ? parseInt(floorMatch[1]) : null,
                            unit_number: numMatch ? numMatch[1] : '',
                        });
                    }
                }
                return results;
            }""")

            self.logger.info(f"Extracted {len(raw)} text blocks from listing page")

            for item in raw:
                pv = item.get("price_value")
                area = item.get("area")
                price_per_sqm = int(pv / area) if pv and area and area > 0 else None
                ext_id = f"osnova-{item.get('unit_number', '')}-{area}-{item.get('floor', '')}"

                items.append({
                    "external_id": ext_id,
                    "title": f"Офис {item.get('unit_number', '')} {area or ''} м²".strip(),
                    "project_name": "ЭМОУШН",
                    "property_type": "офис",
                    "area": area,
                    "price": str(pv) if pv else "по запросу",
                    "price_value": pv,
                    "price_per_sqm": price_per_sqm,
                    "floor": item.get("floor"),
                    "metro_station": "Звенигородская",
                    "metro_distance_min": 5,
                    "property_url": self.base_url,
                    "raw_data": {"text": item.get("text", "")},
                })

        else:
            # Visit each unit page
            for i, link in enumerate(unit_links):
                if i >= 200:  # Safety limit
                    break
                try:
                    self.logger.info(f"  Unit {i+1}/{len(unit_links)}: {link[-60:]}")
                    page.goto(link, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(random.uniform(1.5, 3))

                    unit = page.evaluate("""() => {
                        const text = document.body.innerText;
                        const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                        const priceMatch = text.match(/(?:^|\\n)\\s*(\\d[\\d\\s]+)\\s*₽/m);
                        const floorMatch = text.match(/Этаж\\s*(\\d+)/i);
                        const numMatch = text.match(/№\\s*([А-Яа-яO\\d.]+)/);
                        const typeMatch = text.match(/(Офисное помещение|Торговое помещение|Коммерческое помещение)/i);
                        const corpMatch = text.match(/Корпус\\s*(\\d+)/i);

                        return {
                            area: areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null,
                            price_value: priceMatch ? parseInt(priceMatch[1].replace(/\\s/g, '')) : null,
                            floor: floorMatch ? parseInt(floorMatch[1]) : null,
                            unit_number: numMatch ? numMatch[1] : '',
                            property_type: typeMatch ? typeMatch[1].toLowerCase() : 'офис',
                            corpus: corpMatch ? corpMatch[1] : '',
                        };
                    }""")

                    pv = unit.get("price_value")
                    area = unit.get("area")
                    price_per_sqm = int(pv / area) if pv and area and area > 0 else None

                    # Extract UUID from URL as external_id
                    import re
                    uuid_match = re.search(r'([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})', link, re.IGNORECASE)
                    ext_id = uuid_match.group(1) if uuid_match else f"osnova-{i}"

                    items.append({
                        "external_id": ext_id,
                        "title": f"Офис {unit.get('unit_number', '')} {area or ''} м²".strip(),
                        "project_name": "ЭМОУШН",
                        "property_type": unit.get("property_type", "офис"),
                        "area": area,
                        "price": str(pv) if pv else "по запросу",
                        "price_value": pv if pv and pv > 0 else None,
                        "price_per_sqm": price_per_sqm,
                        "floor": unit.get("floor"),
                        "metro_station": "Звенигородская",
                        "metro_distance_min": 5,
                        "property_url": link,
                        "completion_date": "2026",
                        "raw_data": {"corpus": unit.get("corpus", "")},
                    })

                except Exception as e:
                    self.logger.warning(f"Error scraping unit {link[-40:]}: {e}")

        self.logger.info(f"Total items: {len(items)}")
        return items


if __name__ == "__main__":
    OsnovaScraper().loop()
