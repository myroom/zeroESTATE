"""Скрапер коммерческой недвижимости Самолёт (browser-based)."""

import sys
import os
import re
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper, _AntiBotDetected
from playwright.sync_api import Browser, Page


class SamoletScraper(BrowserScraper):
    slug = "samolet"
    name = "Самолёт"
    base_url = "https://samolet.ru/commercial-realty/"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for page to settle
        time.sleep(random.uniform(2, 5))

        # Check for anti-bot / 403
        if self._detect_anti_bot(page):
            page_text = page.content()[:500]
            self.logger.warning(f"Anti-bot/403 detected on samolet.ru. Page preview: {page_text[:200]}")
            raise _AntiBotDetected(
                "samolet.ru returned 403 Forbidden (Varnish cache block). "
                "A residential proxy is required to access this site."
            )

        # --- API fallback attempt ---
        # Samolet may expose a GraphQL or REST API. If browser scraping fails,
        # these endpoints could be tried as an alternative:
        #
        # GraphQL endpoint (observed on some Samolet subdomains):
        #   POST https://samolet.ru/graphql
        #   Body: {"query": "{ commercialRealty { items { id name area price address } } }"}
        #
        # REST API (speculative):
        #   GET https://api.samolet.ru/api/commercial
        #   GET https://samolet.ru/api/commercial-realty?limit=100
        #
        # These require the same proxy/stealth setup. To try:
        #   response = page.evaluate("""
        #       async () => {
        #           const res = await fetch('/graphql', {
        #               method: 'POST',
        #               headers: {'Content-Type': 'application/json'},
        #               body: JSON.stringify({query: '{ commercialObjects { id title area price } }'})
        #           });
        #           return await res.json();
        #       }
        #   """)
        # --- end API fallback ---

        # Wait for property cards to appear
        try:
            page.wait_for_selector(
                "[class*='card'], [class*='Card'], [class*='item'], [class*='Item'], [class*='property'], [class*='realty']",
                timeout=30000,
            )
        except Exception:
            self.logger.warning("Could not find property cards with common selectors, trying to scroll and wait")

        # Scroll down to trigger lazy loading / pagination
        self._scroll_to_bottom(page)

        # Try clicking "load more" buttons
        self._click_load_more(page)

        # Extract data using page.evaluate
        raw_items = page.evaluate("""() => {
            const results = [];
            // Try multiple possible selectors for property cards
            const selectors = [
                '[class*="CardCommercial"]',
                '[class*="card-commercial"]',
                '[class*="commercial-card"]',
                '[class*="realty-card"]',
                '[class*="CardRealty"]',
                'a[href*="/commercial-realty/"]',
                '[data-test*="card"]',
                '[class*="catalog"] [class*="card"]',
                '[class*="list"] [class*="item"]',
            ];

            let cards = [];
            for (const sel of selectors) {
                const found = document.querySelectorAll(sel);
                if (found.length > 0) {
                    cards = found;
                    break;
                }
            }

            // Fallback: look for links containing /commercial-realty/ with nested content
            if (cards.length === 0) {
                cards = document.querySelectorAll('a[href*="/commercial-realty/"]');
            }

            cards.forEach(card => {
                try {
                    const link = card.tagName === 'A' ? card.href : (card.querySelector('a') ? card.querySelector('a').href : '');
                    const texts = card.innerText || '';

                    // Try to extract area (e.g., "45.5 м²" or "45,5 м²")
                    const areaMatch = texts.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                    // Try to extract price
                    const priceMatch = texts.match(/(\\d[\\d\\s.,]*)\\s*[₽руб]/);
                    let priceValue = null;
                    let priceStr = 'по запросу';
                    if (priceMatch) {
                        const cleaned = priceMatch[1].replace(/\\s/g, '').replace(',', '.');
                        priceValue = Math.round(parseFloat(cleaned));
                        if (!isNaN(priceValue) && priceValue > 0) {
                            priceStr = String(priceValue);
                        } else {
                            priceValue = null;
                        }
                    }

                    // Try to extract floor
                    const floorMatch = texts.match(/(\\d+)\\s*этаж/i);
                    const floor = floorMatch ? parseInt(floorMatch[1]) : null;

                    // Extract project name - usually a heading
                    const heading = card.querySelector('h2, h3, h4, [class*="title"], [class*="name"], [class*="Title"], [class*="Name"]');
                    const projectName = heading ? heading.innerText.trim() : '';

                    // Extract address
                    const addrEl = card.querySelector('[class*="address"], [class*="Address"], [class*="location"], [class*="Location"]');
                    const address = addrEl ? addrEl.innerText.trim() : '';

                    // Extract property type
                    const typeEl = card.querySelector('[class*="type"], [class*="Type"], [class*="category"]');
                    const propertyType = typeEl ? typeEl.innerText.trim() : 'коммерческое';

                    // Extract external_id from URL or data attributes
                    let externalId = card.dataset.id || card.dataset.objectId || '';
                    if (!externalId && link) {
                        const idMatch = link.match(/\\/(\\d+)\\/?(?:\\?|$)/);
                        if (idMatch) externalId = idMatch[1];
                        if (!externalId) {
                            const slugMatch = link.match(/commercial-realty\\/([^\\/\\?]+)/);
                            if (slugMatch) externalId = slugMatch[1];
                        }
                    }
                    if (!externalId) {
                        externalId = 'samolet-' + link.replace(/[^a-zA-Z0-9]/g, '').slice(-30);
                    }

                    results.push({
                        external_id: externalId,
                        project_name: projectName,
                        address: address,
                        area: area,
                        price: priceStr,
                        price_value: priceValue,
                        property_type: propertyType,
                        floor: floor,
                        property_url: link,
                        raw_text: texts.substring(0, 500),
                    });
                } catch(e) {
                    // skip this card
                }
            });
            return results;
        }""")

        self.logger.info(f"Extracted {len(raw_items)} raw items from page")

        for item in raw_items:
            try:
                price_per_sqm = None
                if item.get("price_value") and item.get("area") and item["area"] > 0:
                    price_per_sqm = int(item["price_value"] / item["area"])

                items.append({
                    "external_id": str(item["external_id"]),
                    "project_name": item.get("project_name", ""),
                    "address": item.get("address", ""),
                    "area": item.get("area"),
                    "price": item.get("price", "по запросу"),
                    "price_value": item.get("price_value"),
                    "price_per_sqm": price_per_sqm,
                    "property_type": item.get("property_type", "коммерческое"),
                    "floor": item.get("floor"),
                    "property_url": item.get("property_url", ""),
                    "raw_data": {"raw_text": item.get("raw_text", "")},
                })
            except Exception as e:
                self.logger.warning(f"Error processing item: {e}")
                continue

        self.logger.info(f"Total items collected: {len(items)}")
        return items

    def _scroll_to_bottom(self, page: Page, max_scrolls: int = 20):
        """Scroll down to load lazy-loaded content."""
        for i in range(max_scrolls):
            prev_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            self.logger.info(f"Scrolled page ({i+1}/{max_scrolls})")

    def _click_load_more(self, page: Page, max_clicks: int = 15):
        """Try clicking 'load more' / 'show more' buttons."""
        load_more_selectors = [
            'button:has-text("Показать ещё")',
            'button:has-text("Показать еще")',
            'button:has-text("Загрузить ещё")',
            'button:has-text("Ещё")',
            '[class*="more"] button',
            '[class*="load-more"]',
            '[class*="showMore"]',
        ]
        for _ in range(max_clicks):
            clicked = False
            for sel in load_more_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        time.sleep(random.uniform(1.5, 3))
                        clicked = True
                        self.logger.info("Clicked 'load more' button")
                        break
                except Exception:
                    continue
            if not clicked:
                break


if __name__ == "__main__":
    SamoletScraper().loop()
