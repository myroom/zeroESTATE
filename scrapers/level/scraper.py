"""Скрапер коммерческой недвижимости Level Group (browser-based, React SPA)."""

import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class LevelScraper(BrowserScraper):
    slug = "level"
    name = "Level Group"
    base_url = "https://business.level.ru/projects/"

    # Known CSS class fragments from debug (hashed module classes)
    CARD_SELECTOR = '[class*="ProjectCard"], [class*="cardWrapper"]'

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        all_items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)

        # Let React hydrate
        time.sleep(random.uniform(3, 5))

        # Wait for project cards to render
        try:
            page.wait_for_selector(self.CARD_SELECTOR, timeout=30000)
            self.logger.info("Project cards detected on page")
        except Exception:
            self.logger.warning("Could not find project cards, attempting extraction anyway")

        # Scroll to load any lazy content
        self._scroll_to_bottom(page)

        # Click "show more" if present
        self._click_load_more(page)

        # Extract project cards via page.evaluate with targeted selectors
        raw_items = page.evaluate("""() => {
            const results = [];

            // Target the known Level card classes
            const cards = document.querySelectorAll(
                '[class*="ProjectCard"], [class*="cardWrapper"], [class*="_cardMain_"]'
            );

            // Deduplicate: if cardWrapper is inside ProjectCard, we might get both.
            // Use a Set of card links to avoid duplicates within evaluate.
            const seenLinks = new Set();

            cards.forEach(card => {
                try {
                    // Find the link element
                    const linkEl = card.querySelector('a[class*="cardLink"], a[href*="/projects/"]')
                                || card.closest('a[href*="/projects/"]')
                                || card.querySelector('a');
                    const link = linkEl ? linkEl.href : '';

                    // Skip duplicates and empty cards
                    if (link && seenLinks.has(link)) return;
                    if (link) seenLinks.add(link);

                    const texts = card.innerText || '';
                    if (!texts.trim()) return;

                    // Project name: look for heading inside card
                    const heading = card.querySelector(
                        'h1, h2, h3, h4, [class*="title"], [class*="Title"], [class*="name"], [class*="Name"]'
                    );
                    const projectName = heading ? heading.innerText.trim() : '';

                    // Tags (property type hints like "Офисы", "Торговые", "Ритейл", etc.)
                    const tagEls = card.querySelectorAll(
                        '[class*="cardTagText"], [class*="ProjectCardTags"], [class*="tag"]'
                    );
                    const tags = [];
                    tagEls.forEach(t => {
                        const text = t.innerText.trim();
                        if (text) tags.push(text);
                    });

                    // Metro station
                    const metroEl = card.querySelector(
                        '[class*="metro"], [class*="Metro"], [class*="subway"], [class*="Subway"]'
                    );
                    const metro = metroEl ? metroEl.innerText.trim() : '';

                    // Price: "от X млн ₽" or similar
                    let priceValue = null;
                    let priceStr = 'по запросу';
                    const mlnMatch = texts.match(/(\\d+[.,]?\\d*)\\s*млн/);
                    if (mlnMatch) {
                        priceValue = Math.round(parseFloat(mlnMatch[1].replace(',', '.')) * 1000000);
                        priceStr = 'от ' + mlnMatch[0].trim();
                    }
                    if (!priceValue) {
                        const priceMatch = texts.match(/(\\d[\\d\\s.,]*)\\s*[₽руб\\u20BD]/);
                        if (priceMatch) {
                            const cleaned = priceMatch[1].replace(/\\s/g, '').replace(',', '.');
                            priceValue = Math.round(parseFloat(cleaned));
                            if (!isNaN(priceValue) && priceValue > 0) {
                                priceStr = String(priceValue);
                            } else {
                                priceValue = null;
                            }
                        }
                    }
                    if (/по\\s*запросу/i.test(texts)) {
                        priceStr = 'по запросу';
                        priceValue = null;
                    }

                    // Area: "от X м²"
                    const areaMatch = texts.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                    const area = areaMatch ? parseFloat(areaMatch[1].replace(',', '.')) : null;

                    // Address
                    const addrEl = card.querySelector(
                        '[class*="address"], [class*="Address"], [class*="location"], [class*="Location"]'
                    );
                    const address = addrEl ? addrEl.innerText.trim() : '';

                    // Image
                    const imgEl = card.querySelector('img[class*="cardImage"], img');
                    const imageUrl = imgEl ? (imgEl.src || imgEl.dataset.src || '') : '';

                    // External ID: derive from project URL slug
                    let externalId = '';
                    if (link) {
                        const slugMatch = link.match(/projects?\\/([^\\/\\?#]+)/);
                        if (slugMatch) externalId = slugMatch[1];
                    }
                    if (!externalId) {
                        externalId = card.dataset.id || card.dataset.projectId || '';
                    }
                    if (!externalId) {
                        // Fallback: hash from project name
                        externalId = 'level-' + (projectName || texts)
                            .toLowerCase().replace(/[^a-zа-яё0-9]/g, '-').slice(0, 40);
                    }

                    // Determine property_type from tags
                    let propertyType = 'коммерческое';
                    const tagsLower = tags.join(' ').toLowerCase();
                    if (tagsLower.includes('офис')) propertyType = 'офис';
                    else if (tagsLower.includes('торгов') || tagsLower.includes('ритейл') || tagsLower.includes('retail'))
                        propertyType = 'торговое';
                    else if (tagsLower.includes('свобод') || tagsLower.includes('своб'))
                        propertyType = 'свободное назначение';
                    else if (tagsLower.includes('склад') || tagsLower.includes('storage'))
                        propertyType = 'склад';

                    // Completion date
                    const dateMatch = texts.match(/(\\d\\s*кв(?:артал)?[\\.\\s]*\\d{4}|(?:I{1,3}V?|IV|V?I{0,3})\\s*кв[\\s.]*\\d{4})/i);
                    const completionDate = dateMatch ? dateMatch[1].trim() : '';

                    results.push({
                        external_id: externalId,
                        project_name: projectName,
                        address: address,
                        area: area,
                        price: priceStr,
                        price_value: priceValue,
                        property_type: propertyType,
                        metro_station: metro,
                        tags: tags,
                        completion_date: completionDate,
                        property_url: link,
                        image_url: imageUrl,
                        raw_text: texts.substring(0, 500),
                    });
                } catch(e) {}
            });
            return results;
        }""")

        self.logger.info(f"Extracted {len(raw_items)} raw project cards from listing")

        for item in raw_items:
            try:
                price_per_sqm = None
                if item.get("price_value") and item.get("area") and item["area"] > 0:
                    price_per_sqm = int(item["price_value"] / item["area"])

                all_items.append({
                    "external_id": str(item["external_id"]),
                    "project_name": item.get("project_name", ""),
                    "project_url": item.get("property_url", ""),
                    "title": item.get("project_name", ""),
                    "address": item.get("address", ""),
                    "area": item.get("area"),
                    "price": item.get("price", "по запросу"),
                    "price_value": item.get("price_value"),
                    "price_per_sqm": price_per_sqm,
                    "property_type": item.get("property_type", "коммерческое"),
                    "metro_station": item.get("metro_station", ""),
                    "completion_date": item.get("completion_date", ""),
                    "property_url": item.get("property_url", ""),
                    "image_url": item.get("image_url", ""),
                    "raw_data": {
                        "raw_text": item.get("raw_text", ""),
                        "tags": item.get("tags", []),
                    },
                })
            except Exception as e:
                self.logger.warning(f"Error processing project card: {e}")
                continue

        # Deduplicate by external_id
        seen = set()
        deduped = []
        for item in all_items:
            eid = item["external_id"]
            if eid not in seen:
                seen.add(eid)
                deduped.append(item)

        self.logger.info(f"Total projects collected: {len(deduped)} (after dedup)")
        return deduped

    def _scroll_to_bottom(self, page: Page, max_scrolls: int = 15):
        """Scroll to trigger lazy loading."""
        for i in range(max_scrolls):
            prev_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            self.logger.info(f"Scrolled page ({i+1}/{max_scrolls})")

    def _click_load_more(self, page: Page, max_clicks: int = 10):
        """Click 'show more' / pagination buttons if present."""
        selectors = [
            'button:has-text("Показать ещё")',
            'button:has-text("Показать еще")',
            'button:has-text("Загрузить ещё")',
            '[class*="more"] button',
            '[class*="loadMore"]',
            '[class*="LoadMore"]',
            '[class*="showMore"]',
            '[class*="ShowMore"]',
        ]
        for _ in range(max_clicks):
            clicked = False
            for sel in selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        time.sleep(random.uniform(2, 3))
                        clicked = True
                        self.logger.info("Clicked load-more button")
                        break
                except Exception:
                    continue
            if not clicked:
                break
            # Scroll after loading more content
            self._scroll_to_bottom(page, max_scrolls=3)


if __name__ == "__main__":
    LevelScraper().loop()
