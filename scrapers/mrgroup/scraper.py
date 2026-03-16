"""Скрапер коммерческой недвижимости MR Group (browser-based)."""

import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper, _AntiBotDetected
from playwright.sync_api import Browser, Page


class MRGroupScraper(BrowserScraper):
    slug = "mrgroup"
    name = "MR Group"
    base_url = "https://www.mr-group.ru/commercials/pomeshcheniya/"

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for page to settle and check for anti-bot
        time.sleep(random.uniform(3, 6))

        # Check for ServicePipe anti-bot verification
        if self._detect_servicepipe_antibot(page):
            raise _AntiBotDetected(
                "MR Group uses ServicePipe anti-bot verification (visual puzzle: "
                "'Разверните картинку горизонтально'). This cannot be automated without "
                "a specialized anti-bot service. Try with a different/residential proxy."
            )

        # Also check generic anti-bot
        if self._detect_anti_bot(page):
            page_text = page.content()[:300]
            self.logger.warning(f"Anti-bot detected on mr-group.ru. Page preview: {page_text[:200]}")
            raise _AntiBotDetected(
                "mr-group.ru anti-bot protection detected. "
                "A proxy is required to access this site."
            )

        # Wait for actual content to render
        try:
            page.wait_for_selector(
                "[class*='card'], [class*='Card'], [class*='item'], [class*='Item'], [class*='property'], [class*='commercial']",
                timeout=30000,
            )
        except Exception:
            self.logger.warning("Could not find cards with common selectors, attempting extraction anyway")

        time.sleep(random.uniform(2, 4))

        # Scroll to load all items
        self._scroll_to_bottom(page)

        # Try pagination
        self._click_load_more(page)

        # Extract items
        raw_items = page.evaluate("""() => {
            const results = [];
            const selectors = [
                '[class*="commercial"] [class*="card"]',
                '[class*="Card"]',
                '[class*="catalog"] [class*="item"]',
                '[class*="list"] [class*="card"]',
                'a[href*="/commercials/"]',
                'a[href*="/commercial/"]',
                '[class*="object"]',
                '[data-v-]',
            ];

            let cards = [];
            for (const sel of selectors) {
                const found = document.querySelectorAll(sel);
                if (found.length > 0) {
                    cards = found;
                    break;
                }
            }

            cards.forEach(card => {
                try {
                    const link = card.tagName === 'A' ? card.href : (card.querySelector('a') ? card.querySelector('a').href : '');
                    const texts = card.innerText || '';

                    // Area
                    const areaMatch = texts.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                    // Price
                    const priceMatch = texts.match(/(\\d[\\d\\s.,]*)\\s*[₽руб\\u20BD]/);
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
                    if (texts.includes('по запросу') || texts.includes('По запросу')) {
                        priceStr = 'по запросу';
                        priceValue = null;
                    }

                    // Floor
                    const floorMatch = texts.match(/(\\d+)\\s*этаж/i);
                    const floor = floorMatch ? parseInt(floorMatch[1]) : null;

                    // Project name
                    const heading = card.querySelector('h2, h3, h4, [class*="title"], [class*="Title"], [class*="name"], [class*="Name"]');
                    const projectName = heading ? heading.innerText.trim() : '';

                    // Address
                    const addrEl = card.querySelector('[class*="address"], [class*="Address"], [class*="location"]');
                    const address = addrEl ? addrEl.innerText.trim() : '';

                    // Type
                    const typeEl = card.querySelector('[class*="type"], [class*="Type"], [class*="category"]');
                    const propertyType = typeEl ? typeEl.innerText.trim() : 'коммерческое';

                    // External ID
                    let externalId = card.dataset.id || card.dataset.objectId || '';
                    if (!externalId && link) {
                        const idMatch = link.match(/\\/(\\d+)\\/?(?:\\?|$|#)/);
                        if (idMatch) externalId = idMatch[1];
                        if (!externalId) {
                            const slugMatch = link.match(/(?:commercials?|pomeshcheniya)\\/([^\\/\\?#]+)/);
                            if (slugMatch) externalId = slugMatch[1];
                        }
                    }
                    if (!externalId) {
                        externalId = 'mrgroup-' + (link || texts).replace(/[^a-zA-Z0-9]/g, '').slice(-30);
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
                } catch(e) {}
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

    def _detect_servicepipe_antibot(self, page: Page) -> bool:
        """Detect ServicePipe anti-bot verification page specifically."""
        try:
            content = page.content().lower()
            servicepipe_indicators = [
                "убедиться" in content and "бот" in content,
                "разверните картинку" in content,
                "servicepipe" in content,
                "rotate" in content and "image" in content and "horizontal" in content,
            ]
            detected = any(servicepipe_indicators)
            if detected:
                self.logger.warning(
                    "MR Group requires ServicePipe anti-bot verification that cannot be "
                    "automated without a specialized service. The verification page shows "
                    "a visual puzzle ('Разверните картинку горизонтально') that requires "
                    "human interaction or a specialized anti-captcha service."
                )
            return detected
        except Exception:
            return False

    def _scroll_to_bottom(self, page: Page, max_scrolls: int = 20):
        for i in range(max_scrolls):
            prev_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            self.logger.info(f"Scrolled page ({i+1}/{max_scrolls})")

    def _click_load_more(self, page: Page, max_clicks: int = 15):
        load_more_selectors = [
            'button:has-text("Показать ещё")',
            'button:has-text("Показать еще")',
            'button:has-text("Загрузить ещё")',
            'button:has-text("Ещё")',
            '[class*="more"] button',
            '[class*="load-more"]',
            '[class*="showMore"]',
            '[class*="pagination"] [class*="next"]',
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
    MRGroupScraper().loop()
