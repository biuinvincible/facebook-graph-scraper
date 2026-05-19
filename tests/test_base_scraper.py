"""
Tests for src/scrapers/base.py — BaseScraper
Mock-based tests for all Playwright-dependent methods.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.scrapers.base import BaseScraper
from src.utils.ban_detector import BanType


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_mock_context():
    ctx = AsyncMock()
    page = AsyncMock()
    page.url = "https://www.facebook.com/"
    page.goto = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=0)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.fill = AsyncMock(return_value=None)
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.locator = MagicMock(return_value=AsyncMock(count=AsyncMock(return_value=0)))
    page.is_closed = MagicMock(return_value=False)
    ctx.new_page = AsyncMock(return_value=page)
    return ctx, page


def make_scraper(config=None):
    ctx, page = make_mock_context()
    scraper = BaseScraper(ctx, config or {
        "min_delay": 0.01, "max_delay": 0.05,
        "max_scroll_attempts": 3,
    })
    return scraper, ctx, page


# ─── __init__ ─────────────────────────────────────────────────────────────────

class TestBaseScraper__init__:
    def test_init_stores_context_and_config(self):
        ctx = AsyncMock()
        cfg = {"min_delay": 0.1}
        scraper = BaseScraper(ctx, cfg)
        assert scraper.context is ctx
        assert scraper.cfg is cfg

    def test_creates_ban_detector_and_rate_limiter(self):
        from src.utils.ban_detector import BanDetector
        from src.utils.rate_limiter import AdaptiveRateLimiter
        ctx = AsyncMock()
        scraper = BaseScraper(ctx, {"min_delay": 1.0, "max_delay": 2.0})
        assert isinstance(scraper.ban_detector, BanDetector)
        assert isinstance(scraper.rate_limiter, AdaptiveRateLimiter)


# ─── get_page ─────────────────────────────────────────────────────────────────

class TestGetPage:
    @pytest.mark.asyncio
    async def test_creates_new_page_when_none(self):
        scraper, ctx, page = make_scraper()
        scraper._page = None
        result = await scraper.get_page()
        ctx.new_page.assert_called_once()
        assert result == page

    @pytest.mark.asyncio
    async def test_returns_existing_page_when_open(self):
        scraper, ctx, page = make_scraper()
        existing_page = AsyncMock()
        existing_page.is_closed = MagicMock(return_value=False)
        scraper._page = existing_page
        result = await scraper.get_page()
        ctx.new_page.assert_not_called()
        assert result == existing_page

    @pytest.mark.asyncio
    async def test_creates_new_page_when_closed(self):
        scraper, ctx, page = make_scraper()
        closed_page = AsyncMock()
        closed_page.is_closed = MagicMock(return_value=True)
        scraper._page = closed_page
        new_page = AsyncMock()
        new_page.is_closed = MagicMock(return_value=False)
        ctx.new_page = AsyncMock(return_value=new_page)
        result = await scraper.get_page()
        ctx.new_page.assert_called_once()
        assert result == new_page


# ─── ensure_logged_in ─────────────────────────────────────────────────────────

class TestEnsureLoggedIn:
    @pytest.mark.asyncio
    async def test_returns_false_when_login_in_url(self):
        scraper, ctx, page = make_scraper()
        page.url = "https://www.facebook.com/login"
        page.query_selector = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper.ensure_logged_in()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_checkpoint_disabled(self):
        scraper, ctx, page = make_scraper()
        page.url = "https://www.facebook.com/checkpoint/disabled"
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper.ensure_logged_in()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_feed_found(self):
        scraper, ctx, page = make_scraper()
        page.url = "https://www.facebook.com/"
        feed_el = AsyncMock()
        # Return feed element for the first selector
        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if 'role="feed"' in sel or "feed" in sel.lower():
                return feed_el
            return None
        page.query_selector = AsyncMock(side_effect=mock_qs)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper.ensure_logged_in()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        scraper, ctx, page = make_scraper()
        page.goto = AsyncMock(side_effect=Exception("Navigation error"))
        result = await scraper.ensure_logged_in()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_fb_url_no_login(self):
        scraper, ctx, page = make_scraper()
        page.url = "https://www.facebook.com/"
        # No selectors match, no login form, URL check succeeds
        page.query_selector = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await scraper.ensure_logged_in()
        # When URL is facebook.com and no login detected → True
        assert result is True


# ─── login_with_credentials ───────────────────────────────────────────────────

class TestLoginWithCredentials:
    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        scraper, ctx, page = make_scraper()
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        result = await scraper.login_with_credentials("user@test.com", "pass")
        assert result is False

    @pytest.mark.asyncio
    async def test_calls_fill_with_credentials(self):
        scraper, ctx, page = make_scraper()
        page.url = "https://www.facebook.com/"

        btn = AsyncMock()
        btn.count = AsyncMock(return_value=1)
        btn.click = AsyncMock()
        page.locator = MagicMock(return_value=AsyncMock(
            first=btn,
            count=AsyncMock(return_value=1),
        ))
        mock_btn = MagicMock()
        mock_btn.count = AsyncMock(return_value=1)
        mock_btn.click = AsyncMock()
        locator = MagicMock()
        locator.first = mock_btn
        locator.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=locator)

        page.query_selector = AsyncMock(return_value=AsyncMock())
        with patch.object(scraper, "ensure_logged_in", new_callable=AsyncMock, return_value=True):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("src.scrapers.base.human_delay", new_callable=AsyncMock):
                    result = await scraper.login_with_credentials("user@test.com", "pass")
        page.fill.assert_called()
        assert result is True


# ─── navigate_safely ──────────────────────────────────────────────────────────

class TestNavigateSafely:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 200
        page.goto = AsyncMock(return_value=resp)
        with patch.object(scraper.ban_detector, "check", new_callable=AsyncMock, return_value=BanType.NONE):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_login_wall(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 200
        page.goto = AsyncMock(return_value=resp)
        with patch.object(scraper.ban_detector, "check", new_callable=AsyncMock, return_value=BanType.LOGIN_WALL):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_account_disabled(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 200
        page.goto = AsyncMock(return_value=resp)
        with patch.object(scraper.ban_detector, "check", new_callable=AsyncMock, return_value=BanType.ACCOUNT_DISABLED):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert result is False

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 200
        page.goto = AsyncMock(return_value=resp)
        call_count = [0]
        async def mock_check(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return BanType.RATE_LIMIT
            return BanType.NONE

        with patch.object(scraper.ban_detector, "check", side_effect=mock_check):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                with patch.object(scraper.rate_limiter, "long_pause", new_callable=AsyncMock):
                    result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert call_count[0] >= 2  # retried

    @pytest.mark.asyncio
    async def test_returns_false_on_all_retries_fail(self):
        scraper, ctx, page = make_scraper()
        page.goto = AsyncMock(side_effect=Exception("Network error"))
        with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_checkpoint_ban(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 200
        page.goto = AsyncMock(return_value=resp)
        with patch.object(scraper.ban_detector, "check", new_callable=AsyncMock, return_value=BanType.CHECKPOINT):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                with patch.object(scraper.rate_limiter, "long_pause", new_callable=AsyncMock):
                    result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_429_status(self):
        scraper, ctx, page = make_scraper()
        resp = AsyncMock()
        resp.status = 429
        page.goto = AsyncMock(return_value=resp)
        with patch.object(scraper.ban_detector, "check", new_callable=AsyncMock, return_value=BanType.NONE):
            with patch.object(scraper.rate_limiter, "wait", new_callable=AsyncMock):
                with patch.object(scraper.rate_limiter, "long_pause", new_callable=AsyncMock):
                    result = await scraper.navigate_safely(page, "https://www.facebook.com/page")
        # After 3 retries with 429, should return False
        assert result is False


# ─── dismiss_popups ───────────────────────────────────────────────────────────

class TestDismissPopups:
    @pytest.mark.asyncio
    async def test_dismisses_visible_popups(self):
        scraper, ctx, page = make_scraper()
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=True)
        btn.click = AsyncMock()
        page.query_selector = AsyncMock(return_value=btn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await scraper.dismiss_popups(page)
        btn.click.assert_called()

    @pytest.mark.asyncio
    async def test_skips_invisible_popups(self):
        scraper, ctx, page = make_scraper()
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=False)
        btn.click = AsyncMock()
        page.query_selector = AsyncMock(return_value=btn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await scraper.dismiss_popups(page)
        btn.click.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        scraper, ctx, page = make_scraper()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Should not raise
            await scraper.dismiss_popups(page)


# ─── scroll_and_load ──────────────────────────────────────────────────────────

class TestScrollAndLoad:
    @pytest.mark.asyncio
    async def test_stops_when_height_doesnt_change(self):
        scraper, ctx, page = make_scraper()
        # First call returns 1000, second call returns same 1000 → stops
        page.evaluate = AsyncMock(return_value=1000)
        page.query_selector_all = AsyncMock(return_value=[])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            attempts = await scraper.scroll_and_load(page, target_items=20, pause=0.1)
        # With initial prev_height=0, first scroll will happen, then detects no change
        assert attempts <= 2

    @pytest.mark.asyncio
    async def test_stops_when_enough_items(self):
        scraper, ctx, page = make_scraper()
        heights = [1000, 2000, 3000]
        height_idx = [0]

        async def mock_eval(js):
            if "scrollHeight" in js and "scrollTo" not in js:
                val = heights[min(height_idx[0], len(heights)-1)]
                height_idx[0] += 1
                return val
            return None

        page.evaluate = AsyncMock(side_effect=mock_eval)
        # Return enough articles after first scroll
        articles = [AsyncMock() for _ in range(25)]
        page.query_selector_all = AsyncMock(return_value=articles)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            attempts = await scraper.scroll_and_load(page, target_items=20, pause=0.1)
        # Should stop because enough items found
        assert attempts <= 3

    @pytest.mark.asyncio
    async def test_respects_max_scroll_attempts(self):
        scraper, ctx, page = make_scraper()
        scraper.cfg["max_scroll_attempts"] = 2
        heights = [1000, 2000, 3000, 4000, 5000]
        height_idx = [0]

        async def mock_eval(js):
            if "scrollHeight" in js and "scrollTo" not in js:
                val = heights[min(height_idx[0], len(heights)-1)]
                height_idx[0] += 1
                return val
            return None

        page.evaluate = AsyncMock(side_effect=mock_eval)
        page.query_selector_all = AsyncMock(return_value=[])
        with patch("asyncio.sleep", new_callable=AsyncMock):
            attempts = await scraper.scroll_and_load(page, target_items=100, pause=0.1)
        assert attempts <= 2
