"""Базовый скрапер на Playwright для SPA-сайтов."""

import sys
import os
import time
import random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.base_scraper import BaseScraper
from playwright.sync_api import sync_playwright, Browser, Page
from shared.db import SyncSessionLocal
from shared.models import ScraperConfig

# Realistic user-agents for rotation
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


class BrowserScraper(BaseScraper):
    """Скрапер с Playwright для сайтов, требующих JS-рендеринга."""

    headless: bool = True
    max_retries: int = 3

    def _get_proxy(self) -> dict | None:
        with SyncSessionLocal() as session:
            config = session.query(ScraperConfig).filter_by(source_id=self.source_id).first()
            if config and config.proxy_url:
                return {"server": config.proxy_url}
        return None

    def _detect_anti_bot(self, page: Page) -> bool:
        """Check if the page shows an anti-bot challenge or block."""
        try:
            content = page.content().lower()
            title = page.title().lower()
            url = page.url.lower()

            indicators = [
                # Generic
                "403 forbidden" in content,
                "access denied" in content,
                "доступ" in content and "запрещен" in content,
                # Varnish / CDN blocks
                "varnish" in content and ("403" in content or "запрещен" in content),
                # ServicePipe
                "убедиться" in content and "бот" in content,
                "разверните картинку" in content,
                "servicepipe" in content,
                # Cloudflare
                "checking your browser" in content,
                "cloudflare" in content and "challenge" in content,
                # CAPTCHA
                "captcha" in content,
                "проверка браузера" in content,
                # Challenge pages
                "challenge" in url,
                # DDoS protection
                "ddos" in content and "protect" in content,
            ]
            return any(indicators)
        except Exception:
            return False

    def scrape(self) -> list[dict]:
        proxy = self._get_proxy()
        user_agent = random.choice(_USER_AGENTS)

        for attempt in range(1, self.max_retries + 1):
            self.logger.info(f"Scrape attempt {attempt}/{self.max_retries}")
            try:
                items = self._do_scrape(proxy, user_agent)
                return items
            except _AntiBotDetected as e:
                self.logger.warning(f"Anti-bot detected on attempt {attempt}: {e}")
                if attempt < self.max_retries:
                    wait = random.uniform(5, 15) * attempt
                    self.logger.info(f"Waiting {wait:.0f}s before retry...")
                    time.sleep(wait)
                    # Rotate user-agent on retry
                    user_agent = random.choice(_USER_AGENTS)
                else:
                    if proxy is None:
                        self.logger.warning(
                            "Anti-bot protection detected and NO PROXY configured. "
                            "Configure a proxy in the dashboard (scraper_config.proxy_url) "
                            "to bypass anti-bot protection. Returning empty results."
                        )
                    else:
                        self.logger.warning(
                            "Anti-bot protection detected even with proxy. "
                            "The proxy may be blocked or insufficient. "
                            "Try a different proxy. Returning empty results."
                        )
                    return []
            except Exception as e:
                self.logger.exception(f"Scrape attempt {attempt} failed: {e}")
                if attempt >= self.max_retries:
                    raise
                time.sleep(random.uniform(3, 8))

        return []

    def _do_scrape(self, proxy: dict | None, user_agent: str) -> list[dict]:
        """Single scrape attempt with stealth and anti-bot detection."""
        with sync_playwright() as p:
            launch_args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
            browser = p.chromium.launch(
                headless=self.headless,
                args=launch_args,
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                user_agent=user_agent,
                proxy=proxy,
                extra_http_headers={
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                },
            )
            context.set_default_timeout(60000)
            page = context.new_page()

            # Apply playwright-stealth to hide automation markers
            try:
                from playwright_stealth import stealth_sync
                stealth_sync(page)
                self.logger.info("Playwright stealth applied successfully")
            except ImportError:
                self.logger.warning(
                    "playwright-stealth not installed. Install it with: pip install playwright-stealth. "
                    "Stealth mode helps bypass anti-bot detection."
                )

            try:
                items = self.scrape_with_browser(page, browser)
            finally:
                context.close()
                browser.close()
        return items

    def scrape_with_browser(self, page: Page, browser: Browser) -> list[dict]:
        """Переопределить в дочернем классе."""
        raise NotImplementedError


class _AntiBotDetected(Exception):
    """Raised when anti-bot protection is detected on the page."""
    pass
