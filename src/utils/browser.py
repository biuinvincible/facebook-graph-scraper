"""
Browser management with stealth anti-detection techniques.
Inspired by: MasuRii/FBScrapeIdeas, Ibrahimghali/Facebook-Scraper
"""
import asyncio
import json
import random
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger


# Real browser user agents from 2025
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

SCREEN_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
]


class BrowserManager:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.cookies_file = Path(config.get("cookies_file", "cookies/session.json"))

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self):
        self._playwright = await async_playwright().start()
        proxy_config = None
        proxy_cfg = self.config.get("proxy", {})
        if proxy_cfg.get("enabled") and proxy_cfg.get("server"):
            proxy_config = {"server": proxy_cfg["server"]}

        screen = random.choice(SCREEN_SIZES)
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.get("headless", False),
            slow_mo=self.config.get("slow_mo", 100),
            proxy=proxy_config,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--lang=vi-VN,vi,en-US,en",
                f"--window-size={screen['width']},{screen['height']}",
            ],
        )

        context_options = {
            "viewport": screen,
            "user_agent": random.choice(USER_AGENTS),
            "locale": "vi-VN",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "permissions": ["geolocation"],
            "extra_http_headers": {
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "sec-ch-ua-platform": '"Windows"',
            },
        }

        self._context = await self._browser.new_context(**context_options)
        await self._apply_stealth(self._context)

        # Load saved cookies if available
        if self.cookies_file.exists():
            await self.load_cookies()

        logger.info("Browser started with stealth mode")
        return self._context

    async def _apply_stealth(self, context: BrowserContext):
        """Inject stealth scripts to evade bot detection"""
        await context.add_init_script("""
            // Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

            // Override plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['vi-VN', 'vi', 'en-US', 'en']
            });

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Fake chrome runtime
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            // Override connection
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                })
            });
        """)

    async def new_page(self) -> Page:
        page = await self._context.new_page()
        page.set_default_timeout(self.config.get("timeout", 30000))
        return page

    async def save_cookies(self):
        if not self._context:
            return
        self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
        cookies = await self._context.cookies()
        with open(self.cookies_file, "w") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"Saved {len(cookies)} cookies to {self.cookies_file}")

    async def load_cookies(self):
        if not self._context or not self.cookies_file.exists():
            return
        with open(self.cookies_file) as f:
            cookies = json.load(f)
        await self._context.add_cookies(cookies)
        logger.info(f"Loaded {len(cookies)} cookies from {self.cookies_file}")

    async def close(self):
        if self.config.get("save_session", True):
            await self.save_cookies()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")
