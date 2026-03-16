"""Скрапер коммерческой недвижимости Группа ЛСР (browser-based)."""

import sys
import os
import re
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class LSRScraper(BrowserScraper):
    slug = "lsr"
    name = "Группа ЛСР"
    base_url = "https://www.lsr.ru/msk/kommercheskaya-nedvizhimost/"

    PROJECTS = [
        {"slug": "luchi", "name": "ЛУЧИ", "metro": "Солнцево", "metro_min": 5},
        {"slug": "wave", "name": "ВЕЙВ", "metro": "Борисово", "metro_min": 7},
        {"slug": "parkside", "name": "ПАРКСАЙД", "metro": "Пражская", "metro_min": None},
        {"slug": "zilart-grand", "name": "ЗИЛАРТ ГРАНД", "metro": "ЗИЛ", "metro_min": 5},
        {"slug": "mark", "name": "ЗИЛАРТ МАРК", "metro": "ЗИЛ", "metro_min": 5},
    ]

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        all_items = []

        for proj in self.PROJECTS:
            url = f"{self.base_url}{proj['slug']}/"
            self.logger.info(f"Scraping project: {proj['name']} -> {url}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(3, 5))

                # Scroll to load all table rows
                for _ in range(10):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.5)

                # Extract table data - each row is a unit with: title, area, price, project, corpus, floor, completion, finishing
                raw = page.evaluate("""() => {
                    const results = [];
                    const text = document.body.innerText;

                    // Parse the tabular data from body text
                    // Pattern: "Ритейл №..." followed by area, price, project, corpus, floor, completion, finishing
                    // Split by "Забронировать" which separates each row
                    const blocks = text.split('Забронировать');

                    for (const block of blocks) {
                        // Look for "Ритейл" or "Офис" lines
                        const titleMatch = block.match(/(Ритейл|Офис|ПСН|Помещение)[^\\n]*(?:\\([^)]+\\))?/i);
                        if (!titleMatch) continue;

                        const title = titleMatch[0].trim();

                        // Area: "50.6 м2" or "50,6 м2"
                        const areaMatch = block.match(/(\\d+[.,]?\\d*)\\s*м2/);
                        const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                        // Price: "24 042 994 ₽" - use \\n boundary to avoid m2 digits
                        const priceMatch = block.match(/(?:^|\\n)\\s*(\\d[\\d\\s]+)\\s*₽/m);
                        let priceValue = null;
                        let priceStr = 'по запросу';
                        if (priceMatch) {
                            priceValue = parseInt(priceMatch[1].replace(/\\s/g, ''));
                            if (priceValue > 0) priceStr = String(priceValue);
                            else priceValue = null;
                        }

                        // Corpus: "к. 1-2 (этап 2)" or "к.15 (этап 1)"
                        const corpMatch = block.match(/к\\.?\\s*([\\d-]+(?:\\s*\\([^)]+\\))?)/i);
                        const corpus = corpMatch ? corpMatch[1].trim() : '';

                        // Floor: "эт. 1 / 24"
                        let floor = null, floorTotal = null;
                        const floorMatch = block.match(/эт\\.?\\s*(\\d+)\\s*\\/\\s*(\\d+)/i);
                        if (floorMatch) {
                            floor = parseInt(floorMatch[1]);
                            floorTotal = parseInt(floorMatch[2]);
                        }

                        // Completion: "Сдан" or "3 кв. 2026" etc
                        let completion = '';
                        if (block.includes('Сдан')) completion = 'Сдан';
                        else {
                            const qMatch = block.match(/(\\d)\\s*кв\\.?\\s*(\\d{4})/);
                            if (qMatch) completion = qMatch[1] + ' кв. ' + qMatch[2];
                        }

                        // Finishing: "Без отделки" or "С отделкой"
                        let finishing = '';
                        let hasFinishing = null;
                        if (block.includes('Без отделки')) { finishing = 'Без отделки'; hasFinishing = false; }
                        else if (block.match(/С отделкой|Чистовая|Под ключ/i)) { finishing = 'С отделкой'; hasFinishing = true; }

                        if (!area && !priceValue) continue;

                        results.push({
                            title, area, priceStr, priceValue, corpus, floor, floorTotal,
                            completion, finishing, hasFinishing
                        });
                    }
                    return results;
                }""")

                self.logger.info(f"  Extracted {len(raw)} units from {proj['name']}")

                for item in raw:
                    price_per_sqm = None
                    if item.get("priceValue") and item.get("area") and item["area"] > 0:
                        price_per_sqm = int(item["priceValue"] / item["area"])

                    # Generate external_id from title (contains unit number)
                    ext_id = re.sub(r'[^a-zA-Z0-9а-яА-ЯёЁ_-]', '', item.get("title", ""))
                    if not ext_id:
                        ext_id = f"lsr-{proj['slug']}-{item.get('area','')}-{item.get('floor','')}-{item.get('priceValue','')}"

                    all_items.append({
                        "external_id": ext_id,
                        "title": item.get("title", ""),
                        "project_name": proj["name"],
                        "project_url": url,
                        "property_url": url,
                        "property_type": "ритейл" if "Ритейл" in item.get("title", "") else "коммерческое",
                        "address": "",
                        "metro_station": proj["metro"],
                        "metro_distance_min": proj["metro_min"],
                        "area": item.get("area"),
                        "price": item.get("priceStr", "по запросу"),
                        "price_value": item.get("priceValue"),
                        "price_per_sqm": price_per_sqm,
                        "floor": item.get("floor"),
                        "floor_total": item.get("floorTotal"),
                        "completion_date": item.get("completion", ""),
                        "finishing": item.get("finishing", ""),
                        "has_finishing": item.get("hasFinishing"),
                        "status": "в продаже",
                        "raw_data": {"corpus": item.get("corpus", ""), "project_slug": proj["slug"]},
                    })

            except Exception as e:
                self.logger.warning(f"Error scraping {proj['name']}: {e}")

        # Deduplicate
        seen = set()
        deduped = []
        for item in all_items:
            eid = item["external_id"]
            if eid and eid not in seen:
                seen.add(eid)
                deduped.append(item)

        self.logger.info(f"Total items: {len(deduped)} (before dedup: {len(all_items)})")
        return deduped


if __name__ == "__main__":
    LSRScraper().loop()
