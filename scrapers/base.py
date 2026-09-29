"""Base scraper using Playwright with anti-detect features and human-like interactions."""
import asyncio
import random
import logging
from typing import Optional, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

try:
    from playwright_stealth import Stealth
except ImportError:
    Stealth = None

from core.models import Lead

logger = logging.getLogger(__name__)


class BaseScraper:
    """Base class for Map Scrapers with browser stealth and scrolling capabilities."""

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[Dict[str, str]] = None,
        slow_mo: int = 50,
        timeout: int = 30000,
    ):
        self.headless = headless
        self.proxy = proxy
        self.slow_mo = slow_mo
        self.timeout = timeout
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_running = False

    async def start(self) -> Page:
        """Starts Playwright browser session with anti-detection configurations."""
        self.playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--window-position=0,0",
            "--ignore-certifcate-errors",
            "--ignore-certifcate-errors-spki-list",
            "--disable-dev-shm-usage",
            "--lang=ru-RU,ru",
        ]

        browser_kwargs: Dict[str, Any] = {
            "headless": self.headless,
            "args": launch_args,
            "slow_mo": self.slow_mo,
        }

        if self.proxy:
            browser_kwargs["proxy"] = self.proxy

        self.browser = await self.playwright.chromium.launch(**browser_kwargs)

        # Context settings
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

        self.context = await self.browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1400, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            geolocation={"latitude": 55.7558, "longitude": 37.6173},
            permissions=["geolocation"],
            color_scheme="light",
        )

        # Anti-bot detection scripts
        await self.context.add_init_script("""
            // Overwrite webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            // Overwrite languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ru-RU', 'ru', 'en-US', 'en']
            });
            // Overwrite plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            // Chrome runtime mock
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
        """)

        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout)

        # Block ad trackers, telemetry, and cookie-syncing networks to prevent antivirus alerts
        # and significantly speed up page loading.
        AD_TRACKER_DOMAINS = [
            "uuidksinc.net",
            "doubleclick.net",
            "google-analytics.com",
            "googletagmanager.com",
            "mc.yandex.ru",
            "an.yandex.ru",
            "top-fwz1.mail.ru",
            "adriver.ru",
            "tns-counter.ru",
            "criteo.com",
            "buzzoola.com",
            "soloway.ru",
            "relap.io",
            "sape.ru",
            "hybrid.ai",
            "mytarget.com",
            "yadro.ru",
            "scorecardresearch.com",
        ]

        async def route_interceptor(route):
            req_url = route.request.url.lower()
            if any(domain in req_url for domain in AD_TRACKER_DOMAINS):
                await route.abort()
            else:
                await route.continue_()

        await self.context.route("**/*", route_interceptor)

        if Stealth:
            try:
                stealth = Stealth()
                await stealth.apply_stealth_async(self.page)
            except Exception as e:
                logger.debug(f"Stealth injection notice: {e}")

        self.is_running = True
        return self.page

    async def close(self):
        """Closes browser and stops Playwright."""
        self.is_running = False
        try:
            if self.page:
                await self.page.close()
        except Exception:
            pass

        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass

        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

    async def human_delay(self, min_sec: float = 1.0, max_sec: float = 2.5):
        """Random human-like pause."""
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def smooth_scroll_container(self, selector: str, distance: int = 400):
        """Smoothly scrolls a container or page."""
        if not self.page:
            return
        try:
            await self.page.evaluate(
                """([sel, dist]) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.scrollBy({ top: dist, behavior: 'smooth' });
                    } else {
                        window.scrollBy({ top: dist, behavior: 'smooth' });
                    }
                }""",
                [selector, distance],
            )
        except Exception:
            pass
