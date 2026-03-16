"""Скрапер коммерческой недвижимости Брусника (browser-based)."""

import sys
import os
import re
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class BrusnikaScraper(BrowserScraper):
    slug = "brusnika"
    name = "Брусника"
    base_url = "https://moskva.brusnika.ru/commercial/"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(random.uniform(3, 5))

        # Click "Показать N помещений" button to reveal the full list
        try:
            show_btn = page.query_selector('button:has-text("Показать"), a:has-text("Показать")')
            if show_btn and show_btn.is_visible():
                show_btn.click()
                self.logger.info("Clicked 'Показать' button")
                time.sleep(3)
        except Exception:
            pass

        # Try clicking "Смотреть все" link
        try:
            see_all = page.query_selector('a:has-text("Смотреть все")')
            if see_all and see_all.is_visible():
                see_all.click()
                self.logger.info("Clicked 'Смотреть все'")
                time.sleep(3)
        except Exception:
            pass

        # Scroll to load all content
        for _ in range(10):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)

        # Extract commercial property links
        raw_items = page.evaluate("""() => {
            const results = [];
            // Find all links to commercial/office/{id}
            const links = document.querySelectorAll('a[href*="/commercial/office/"]');

            links.forEach(link => {
                try {
                    const href = link.href;
                    const text = link.innerText || '';
                    if (!text.trim() || text.trim().length < 10) return;

                    // Extract ID from URL
                    const idMatch = href.match(/office\\/(\\d+)/);
                    const externalId = idMatch ? idMatch[1] : '';
                    if (!externalId) return;

                    // Parse text like: "Помещение №1, 144,6 м2 / 62 030 000 руб. / Квартал Герцена Этаж 1 из 30 / Дом 2 Срок сдачи 4 квартал 2027"
                    // Area: "144,6 м2" or "144.6 м²"
                    const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                    // Price: "62 030 000 руб" or numbers + руб/₽
                    // Use \\n or line boundary to avoid capturing trailing digits from area "м2"
                    const priceMatch = text.match(/(?:^|\\n)\\s*(\\d[\\d\\s]+)\\s*руб/im);
                    let priceValue = null;
                    let priceStr = 'по запросу';
                    if (priceMatch) {
                        priceValue = parseInt(priceMatch[1].replace(/\\s/g, ''));
                        if (priceValue > 0) {
                            priceStr = String(priceValue);
                        } else {
                            priceValue = null;
                        }
                    }

                    // Project name: "Квартал Герцена" or "Первый квартал" or "Квартал «Метроном»"
                    let projectName = '';
                    const projMatch = text.match(/(Квартал[^Э]*?|Первый квартал)\\s*(?=Этаж|Дом|$)/i);
                    if (projMatch) {
                        projectName = projMatch[1].trim();
                    }

                    // Floor: "Этаж 1 из 30"
                    let floor = null;
                    let floorTotal = null;
                    const floorMatch = text.match(/Этаж\\s*(\\d+)\\s*из\\s*(\\d+)/i);
                    if (floorMatch) {
                        floor = parseInt(floorMatch[1]);
                        floorTotal = parseInt(floorMatch[2]);
                    }

                    // Building: "Дом 2"
                    let building = '';
                    const buildMatch = text.match(/Дом\\s*(\\d+)/i);
                    if (buildMatch) building = buildMatch[1];

                    // Completion: "Срок сдачи 4 квартал 2027"
                    let completionDate = '';
                    const dateMatch = text.match(/Срок\\s*сдачи\\s*(.+?)$/i);
                    if (dateMatch) completionDate = dateMatch[1].trim();

                    // Title from first line
                    const title = text.split('\\n')[0].trim();

                    results.push({
                        external_id: externalId,
                        title: title,
                        project_name: projectName,
                        area: area,
                        price: priceStr,
                        price_value: priceValue,
                        floor: floor,
                        floor_total: floorTotal,
                        building: building,
                        completion_date: completionDate,
                        property_url: href,
                        raw_text: text.substring(0, 500),
                    });
                } catch(e) {}
            });

            return results;
        }""")

        self.logger.info(f"Extracted {len(raw_items)} items from page")

        # Also try scraping project filter pages for more data
        if len(raw_items) < 20:
            self.logger.info("Few items found, trying filter pages...")
            for filter_url in [
                "https://moskva.brusnika.ru/commercial/filter/?view=buy&rent_active=false",
            ]:
                try:
                    page.goto(filter_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(5)
                    for _ in range(10):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1)

                    more_items = page.evaluate("""() => {
                        const results = [];
                        const links = document.querySelectorAll('a[href*="/commercial/office/"]');
                        links.forEach(link => {
                            try {
                                const href = link.href;
                                const text = link.innerText || '';
                                const idMatch = href.match(/office\\/(\\d+)/);
                                const externalId = idMatch ? idMatch[1] : '';
                                if (!externalId || text.length < 10) return;

                                const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                                const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;
                                const priceMatch = text.match(/(\\d[\\d\\s]+)\\s*руб/i);
                                let priceValue = null, priceStr = 'по запросу';
                                if (priceMatch) {
                                    priceValue = parseInt(priceMatch[1].replace(/\\s/g, ''));
                                    if (priceValue > 0) priceStr = String(priceValue);
                                    else priceValue = null;
                                }
                                const floorMatch = text.match(/Этаж\\s*(\\d+)\\s*из\\s*(\\d+)/i);
                                const dateMatch = text.match(/Срок\\s*сдачи\\s*(.+?)$/i);

                                results.push({
                                    external_id: externalId,
                                    title: text.split('\\n')[0].trim(),
                                    project_name: '',
                                    area: area,
                                    price: priceStr,
                                    price_value: priceValue,
                                    floor: floorMatch ? parseInt(floorMatch[1]) : null,
                                    floor_total: floorMatch ? parseInt(floorMatch[2]) : null,
                                    completion_date: dateMatch ? dateMatch[1].trim() : '',
                                    property_url: href,
                                    raw_text: text.substring(0, 500),
                                });
                            } catch(e) {}
                        });
                        return results;
                    }""")
                    self.logger.info(f"Filter page: {len(more_items)} items")
                    raw_items.extend(more_items)
                except Exception as e:
                    self.logger.warning(f"Filter page error: {e}")

        # Deduplicate and map
        seen = set()
        for item in raw_items:
            eid = str(item.get("external_id", ""))
            if not eid or eid in seen:
                continue
            seen.add(eid)

            price_per_sqm = None
            pv = item.get("price_value")
            area = item.get("area")
            if pv and area and area > 0:
                price_per_sqm = int(pv / area)

            items.append({
                "external_id": eid,
                "title": item.get("title", ""),
                "project_name": item.get("project_name", ""),
                "address": "",
                "area": area,
                "price": item.get("price", "по запросу"),
                "price_value": pv,
                "price_per_sqm": price_per_sqm,
                "property_type": "коммерческое",
                "floor": item.get("floor"),
                "floor_total": item.get("floor_total"),
                "completion_date": item.get("completion_date", ""),
                "property_url": item.get("property_url", ""),
                "raw_data": {"raw_text": item.get("raw_text", ""), "building": item.get("building", "")},
            })

        self.logger.info(f"Total unique items: {len(items)}")
        return items


if __name__ == "__main__":
    BrusnikaScraper().loop()
