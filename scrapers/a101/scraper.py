"""Скрапер коммерческой недвижимости А101 (browser-based, Nuxt 3 SPA)."""

import sys
import os
import re
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.browser_scraper import BrowserScraper
from playwright.sync_api import Browser, Page


class A101Scraper(BrowserScraper):
    slug = "a101"
    name = "А101"
    base_url = "https://a101.ru/commercial/pomeshheniya-i-uchastki?order=actual_price&deal=sell"

    # Each card is an <li class="card-list-item"> containing an <article>
    CARD_SELECTOR = 'li.card-list-item'

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        all_items = []

        self.logger.info(f"Navigating to {self.base_url}")
        page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for cards
        try:
            page.wait_for_selector(self.CARD_SELECTOR, timeout=30000)
            self.logger.info("Cards detected on page")
        except Exception:
            self.logger.warning("Card selector not found, trying anyway")
            time.sleep(5)

        # Infinite scroll: scroll to the loader at bottom to trigger loading
        prev_count = 0
        stale_rounds = 0
        for scroll_round in range(200):
            current_count = page.evaluate("document.querySelectorAll('li.card-list-item').length")
            if scroll_round % 5 == 0:
                self.logger.info(f"Scroll round {scroll_round + 1}: {current_count} cards loaded")
            if current_count == prev_count:
                stale_rounds += 1
                if stale_rounds >= 5:
                    break
            else:
                stale_rounds = 0
            prev_count = current_count
            # Scroll the loader into view to trigger loading
            page.evaluate("""() => {
                const loader = document.querySelector('[class*="pagination_11ckw"], [class*="VLoader"]');
                if (loader) {
                    loader.scrollIntoView({behavior: 'instant'});
                } else {
                    window.scrollTo(0, document.body.scrollHeight);
                }
            }""")
            time.sleep(random.uniform(1, 2))

        self.logger.info(f"Total cards after scrolling: {prev_count}")

        # Extract all cards
        raw_items = page.evaluate("""() => {
            const results = [];
            const cards = document.querySelectorAll('li.card-list-item');

            cards.forEach(card => {
                    try {
                        const text = card.innerText || '';
                        if (!text.trim()) return;

                        // --- Link / URL ---
                        const linkEl = card.querySelector('a[href]');
                        const link = linkEl ? linkEl.href : '';

                        // --- Image ---
                        const imgEl = card.querySelector('img[src]');
                        const imageUrl = imgEl ? imgEl.src : '';

                        // --- Project name ---
                        // Appears as first distinct line, often a heading or bold text
                        // Known patterns: "Дзен-кварталы", "Родные кварталы"
                        let projectName = '';
                        const headingEl = card.querySelector(
                            'h2, h3, h4, [class*="title"], [class*="Title"], [class*="name"], [class*="Name"]'
                        );
                        if (headingEl) {
                            projectName = headingEl.innerText.trim();
                        }
                        // Fallback: first line of text if heading is empty
                        if (!projectName) {
                            const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                            if (lines.length > 0 && !lines[0].match(/^[\\d\\s₽]/)) {
                                projectName = lines[0];
                            }
                        }

                        // --- Floor: "эт. X из Y" ---
                        let floor = null;
                        let floorTotal = null;
                        const floorMatch = text.match(/эт\\.?\\s*(\\d+)\\s*из\\s*(\\d+)/i);
                        if (floorMatch) {
                            floor = parseInt(floorMatch[1]);
                            floorTotal = parseInt(floorMatch[2]);
                        } else {
                            const simpleFloor = text.match(/(\\d+)\\s*этаж/i);
                            if (simpleFloor) floor = parseInt(simpleFloor[1]);
                        }

                        // --- Building/corpus: "корп. X" ---
                        let building = '';
                        const corpMatch = text.match(/корп\\.?\\s*([\\d.]+)/i);
                        if (corpMatch) building = corpMatch[1];

                        // --- Metro ---
                        let metroStation = '';
                        let metroDistanceMin = null;
                        // Pattern: "М StationName" or metro icon + name
                        const metroMatch = text.match(/М\\s+([А-Яа-яЁё\\s-]+?)\\n/);
                        if (metroMatch) {
                            metroStation = metroMatch[1].trim();
                        }
                        // Distance: "до X мин. пешком" or "до X мин. на машине"
                        const metroDistMatch = text.match(/до\\s+(\\d+)\\s*мин\\.?\\s*(пешком|на машине)?/i);
                        if (metroDistMatch) {
                            metroDistanceMin = parseInt(metroDistMatch[1]);
                        }

                        // --- Property type + area ---
                        // "Торговое помещ. 24.6 м²" or "Офисное помещ. 70.9 м²"
                        let propertyType = 'коммерческое';
                        let area = null;
                        const typeAreaMatch = text.match(/(Торговое|Офисное|Свободного назначения|Помещение|Производственное|Складское)[^\\d]*(\\d+[.,]?\\d*)\\s*м[²2]/i);
                        if (typeAreaMatch) {
                            propertyType = typeAreaMatch[1].trim();
                            area = parseFloat(typeAreaMatch[2].replace(',', '.'));
                        } else {
                            // Just area
                            const areaMatch = text.match(/(\\d+[.,]?\\d*)\\s*м[²2]/);
                            if (areaMatch) {
                                area = parseFloat(areaMatch[1].replace(',', '.'));
                            }
                        }

                        // --- Prices ---
                        // Main price: "16 138 584 ₽" — could be multiple (current + old crossed out)
                        let priceValue = null;
                        let priceStr = 'по запросу';
                        let pricePerSqm = null;

                        // Price per sqm: "от 656 040 ₽/м²"
                        const psmMatch = text.match(/(\\d[\\d\\s]*)\\s*₽\\/м[²2]/);
                        if (psmMatch) {
                            pricePerSqm = parseInt(psmMatch[1].replace(/\\s/g, ''));
                        }

                        // Main price (exclude the per-sqm line)
                        // Find all "NNN ₽" patterns that are NOT followed by /м²
                        const priceRegex = /(\\d[\\d\\s]{2,})\\s*₽(?!\\/м)/g;
                        let priceMatches = [];
                        let m;
                        while ((m = priceRegex.exec(text)) !== null) {
                            const val = parseInt(m[1].replace(/\\s/g, ''));
                            if (val > 10000) priceMatches.push(val);
                        }

                        if (priceMatches.length > 0) {
                            // First price is typically the current (possibly discounted) price
                            priceValue = priceMatches[0];
                            priceStr = String(priceValue);
                        }

                        if (text.match(/по запросу/i)) {
                            priceStr = 'по запросу';
                            priceValue = null;
                        }

                        // Calculate price_per_sqm if not found but we have price and area
                        if (!pricePerSqm && priceValue && area && area > 0) {
                            pricePerSqm = Math.round(priceValue / area);
                        }

                        // --- Discount ---
                        let discount = '';
                        const discountMatch = text.match(/-\\s*(\\d+)\\s*%/);
                        if (discountMatch) {
                            discount = '-' + discountMatch[1] + '%';
                        }

                        // --- Completion date / status ---
                        let completionDate = '';
                        const completionMatch = text.match(/Срок\\s*сдачи:\\s*(.+?)(?:\\n|$)/i);
                        if (completionMatch) {
                            completionDate = completionMatch[1].trim();
                        } else if (text.includes('Дом сдан')) {
                            completionDate = 'Дом сдан';
                        } else if (text.includes('Дом строится')) {
                            completionDate = 'Дом строится';
                        }
                        // Also try "N кв. YYYY"
                        if (!completionDate) {
                            const qMatch = text.match(/(\\d)\\s*кв\\.?\\s*(\\d{4})/);
                            if (qMatch) completionDate = qMatch[1] + ' кв. ' + qMatch[2];
                        }

                        // --- Finishing ---
                        let finishing = '';
                        let hasFinishing = null;
                        if (text.includes('Без отделки')) {
                            finishing = 'Без отделки';
                            hasFinishing = false;
                        } else if (text.match(/С отделкой|Чистовая|Под ключ/i)) {
                            const fMatch = text.match(/(С отделкой|Чистовая|Под ключ|Предчистовая)/i);
                            finishing = fMatch ? fMatch[1] : 'С отделкой';
                            hasFinishing = true;
                        }

                        // --- External ID from placement URL ---
                        let externalId = '';
                        const allLinks = Array.from(card.querySelectorAll('a[href*="placement/"]'));
                        for (const a of allLinks) {
                            const m = a.href.match(/placement\\/([\\d]+)/);
                            if (m) { externalId = m[1]; break; }
                        }
                        // Try data attributes
                        if (!externalId) {
                            externalId = card.dataset.id || card.dataset.objectId || '';
                        }
                        // Fallback
                        if (!externalId) {
                            const key = [projectName, building, floor, area, priceValue]
                                .filter(v => v !== null && v !== undefined && v !== '').join('-');
                            externalId = 'a101-' + key.replace(/[^a-zA-Z0-9а-яА-ЯёЁ.-]/g, '').slice(0, 80);
                        }
                        // Skip cards with no useful data
                        if (!area && !priceValue && !floor) return;
                        // Use placement URL as property_url
                        if (!link) {
                            for (const a of allLinks) {
                                if (a.href.includes('placement/')) { link = a.href; break; }
                            }
                        }

                        // --- Status ---
                        let status = 'в продаже';
                        if (text.match(/забронирован/i)) status = 'бронь';
                        if (text.match(/продано/i)) status = 'продано';

                        results.push({
                            external_id: externalId,
                            project_name: projectName,
                            building: building,
                            area: area,
                            price: priceStr,
                            price_value: priceValue,
                            price_per_sqm: pricePerSqm,
                            property_type: propertyType,
                            floor: floor,
                            floor_total: floorTotal,
                            metro_station: metroStation,
                            metro_distance_min: metroDistanceMin,
                            completion_date: completionDate,
                            finishing: finishing,
                            has_finishing: hasFinishing,
                            discount: discount,
                            status: status,
                            property_url: link,
                            image_url: imageUrl,
                            raw_text: text.substring(0, 800),
                        });
                    } catch(e) {
                        // skip broken card
                    }
                });
                return results;
            }""")

        self.logger.info(f"Extracted {len(raw_items)} cards")

        for item in raw_items:
                try:
                    all_items.append({
                        "external_id": str(item.get("external_id", "")),
                        "project_name": item.get("project_name", ""),
                        "title": self._build_title(item),
                        "address": "",
                        "area": item.get("area"),
                        "price": item.get("price", "по запросу"),
                        "price_value": item.get("price_value"),
                        "price_per_sqm": item.get("price_per_sqm"),
                        "property_type": item.get("property_type", "коммерческое"),
                        "floor": item.get("floor"),
                        "floor_total": item.get("floor_total"),
                        "metro_station": item.get("metro_station", ""),
                        "metro_distance_min": item.get("metro_distance_min"),
                        "completion_date": item.get("completion_date", ""),
                        "finishing": item.get("finishing", ""),
                        "has_finishing": item.get("has_finishing"),
                        "status": item.get("status", ""),
                        "property_url": item.get("property_url", ""),
                        "image_url": item.get("image_url", ""),
                        "raw_data": {
                            "raw_text": item.get("raw_text", ""),
                            "building": item.get("building", ""),
                            "discount": item.get("discount", ""),
                        },
                    })
                except Exception as e:
                    self.logger.warning(f"Error processing item: {e}")
                    continue

        # Deduplicate by external_id
        seen = set()
        deduped = []
        for item in all_items:
            eid = item["external_id"]
            if eid and eid not in seen:
                seen.add(eid)
                deduped.append(item)

        self.logger.info(f"Total items collected: {len(deduped)} (before dedup: {len(all_items)})")
        return deduped

    @staticmethod
    def _build_title(item: dict) -> str:
        """Build a human-readable title from card data."""
        parts = []
        ptype = item.get("property_type", "")
        if ptype:
            parts.append(ptype)
        area = item.get("area")
        if area:
            parts.append(f"{area} м²")
        building = item.get("building", "")
        if building:
            parts.append(f"корп. {building}")
        return ", ".join(parts) if parts else ""

    def _scroll_to_bottom(self, page: Page, max_scrolls: int = 20):
        """Incrementally scroll to bottom to trigger lazy loading."""
        for i in range(max_scrolls):
            prev_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(0.5, 1.0))
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break



if __name__ == "__main__":
    A101Scraper().loop()
