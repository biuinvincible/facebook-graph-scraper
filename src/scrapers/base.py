"""
Base scraper class with login handling, ban detection, and rate limiting.
"""
import asyncio
from typing import Optional, Dict, Any
from playwright.async_api import Page, BrowserContext
from loguru import logger

from ..utils.helpers import human_delay, micro_delay
from ..utils.ban_detector import BanDetector, BanType
from ..utils.rate_limiter import AdaptiveRateLimiter


class BaseScraper:
    FB_BASE = "https://www.facebook.com"
    MBASIC = "https://mbasic.facebook.com"

    def __init__(self, context: BrowserContext, config: Dict[str, Any]):
        self.context = context
        self.cfg = config
        self._page: Optional[Page] = None
        self.ban_detector = BanDetector()
        self.rate_limiter = AdaptiveRateLimiter(
            min_delay=config.get("min_delay", 1.5),
            max_delay=config.get("max_delay", 4.0),
        )

    async def get_page(self) -> Page:
        if not self._page or self._page.is_closed():
            self._page = await self.context.new_page()
        return self._page

    async def ensure_logged_in(self) -> bool:
        """Check if we have an active Facebook session"""
        page = await self.get_page()
        try:
            await page.goto(f"{self.FB_BASE}/", wait_until="domcontentloaded")
            await asyncio.sleep(3)

            url = page.url
            # Bị disabled hoặc checkpoint rõ ràng
            if "checkpoint/disabled" in url:
                logger.error("Account disabled!")
                return False
            if "login" in url and "two_step" not in url:
                return False

            # Nếu URL là facebook.com (không có /login) thì có thể đã vào
            # Chờ thêm để feed load
            await asyncio.sleep(2)

            # Kiểm tra feed hoặc các indicator của logged-in state
            for sel in [
                '[role="feed"]',
                '[data-pagelet="Feed"]',
                '[data-pagelet="NewsFeed"]',
                '[data-pagelet="ProfileTimeline"]',
                'div[role="navigation"]',           # top nav chỉ xuất hiện khi login
                '[aria-label="Facebook"]',
            ]:
                el = await page.query_selector(sel)
                if el:
                    logger.info("Already logged in")
                    return True

            # Kiểm tra xem trang login có hiện không
            login_form = await page.query_selector('[name="email"][name="pass"], form#login_form')
            if login_form:
                return False

            # URL là facebook.com và không có login form → có thể đã vào
            if "facebook.com" in url and "login" not in url and "checkpoint" not in url:
                logger.info("Logged in (URL check)")
                return True

            logger.warning("Not logged in — attempting to check session")
            return False
        except Exception as e:
            logger.error(f"Login check failed: {e}")
            return False

    async def login_with_credentials(self, email: str, password: str) -> bool:
        """Login with email/password. Dùng page.fill() để tránh visibility issues."""
        page = await self.get_page()
        try:
            await page.goto(f"{self.FB_BASE}/login", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Dùng page.fill() — không cần element visible, điền thẳng vào DOM
            await page.wait_for_selector('[name="email"]', timeout=10000)
            await page.fill('[name="email"]', "")       # clear trước
            await human_delay(0.3, 0.6)
            await page.fill('[name="email"]', email)

            await human_delay(0.5, 1.0)

            await page.fill('[name="pass"]', "")
            await human_delay(0.3, 0.6)
            await page.fill('[name="pass"]', password)

            await human_delay(0.8, 1.5)

            # Submit
            submitted = False
            for btn_sel in ['[name="login"]', 'button[type="submit"]', 'input[type="submit"]']:
                try:
                    btn = page.locator(btn_sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        submitted = True
                        break
                except Exception:
                    continue
            if not submitted:
                await page.keyboard.press("Enter")

            # Chờ redirect
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(3)

            return await self.ensure_logged_in()

        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    async def navigate_safely(self, page: Page, url: str, wait: str = "domcontentloaded") -> bool:
        """Navigate with ban detection, rate limiting, and retry"""
        await self.rate_limiter.wait()

        for attempt in range(3):
            try:
                resp = await page.goto(url, wait_until=wait, timeout=30000)

                # Check for ban after navigation
                ban = await self.ban_detector.check(page)
                if ban == BanType.RATE_LIMIT:
                    self.rate_limiter.on_throttle()
                    await self.rate_limiter.long_pause(seconds=60)
                    continue
                elif ban in (BanType.CHECKPOINT, BanType.CAPTCHA):
                    logger.error(f"Checkpoint/CAPTCHA detected at {url} — needs manual intervention")
                    self.rate_limiter.on_ban()
                    await self.rate_limiter.long_pause(seconds=120)
                    return False
                elif ban == BanType.LOGIN_WALL:
                    logger.warning("Login wall — session may have expired")
                    return False
                elif ban == BanType.ACCOUNT_DISABLED:
                    logger.error("Account disabled!")
                    return False

                if resp and resp.status < 400:
                    self.rate_limiter.on_success()
                    return True

                if resp and resp.status == 429:
                    self.rate_limiter.on_throttle()
                    await self.rate_limiter.long_pause(seconds=90)
                    continue

                logger.warning(f"HTTP {resp.status if resp else 'None'} for {url}")

            except Exception as e:
                logger.warning(f"Navigation attempt {attempt+1} failed for {url}: {e}")
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))

        return False

    async def dismiss_popups(self, page: Page):
        """Dismiss common Facebook popups"""
        popup_selectors = [
            '[aria-label="Đóng"]',
            '[aria-label="Close"]',
            '[data-testid="cookie-policy-manage-dialog-accept-button"]',
            'div[role="dialog"] div[role="button"]:has-text("Not Now")',
            'div[role="dialog"] div[role="button"]:has-text("Bây giờ không")',
        ]
        for sel in popup_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                continue

    async def scroll_and_load(self, page: Page, target_items: int = 20, pause: float = 2.0) -> int:
        """Scroll page to load more items, return number of scroll attempts"""
        prev_height = 0
        attempts = 0
        max_attempts = self.cfg.get("max_scroll_attempts", 50)

        while attempts < max_attempts:
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(pause)

            # Check if we might have enough
            items = await page.query_selector_all('[role="article"]')
            if len(items) >= target_items:
                break

            prev_height = curr_height
            attempts += 1

        return attempts
