"""
Tests for src/utils/browser.py — BrowserManager
Mock-based tests that avoid launching real browsers.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from src.utils.browser import BrowserManager


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_mock_playwright():
    """Create a mock Playwright instance."""
    pw = AsyncMock()
    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()

    browser.new_context = AsyncMock(return_value=context)
    context.new_page = AsyncMock(return_value=page)
    context.add_init_script = AsyncMock(return_value=None)
    context.add_cookies = AsyncMock(return_value=None)
    context.cookies = AsyncMock(return_value=[{"name": "c_user", "value": "12345"}])
    context.close = AsyncMock(return_value=None)
    browser.close = AsyncMock(return_value=None)
    pw.chromium = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock(return_value=None)
    page.set_default_timeout = MagicMock(return_value=None)

    return pw, browser, context, page


# ─── __init__ ─────────────────────────────────────────────────────────────────

class TestBrowserManagerInit:
    def test_init_stores_config(self):
        cfg = {"headless": True, "cookies_file": "cookies/test.json"}
        bm = BrowserManager(cfg)
        assert bm.config is cfg

    def test_init_sets_cookies_file_path(self):
        cfg = {"cookies_file": "cookies/session.json"}
        bm = BrowserManager(cfg)
        assert bm.cookies_file == Path("cookies/session.json")

    def test_init_default_cookies_file(self):
        bm = BrowserManager({})
        assert bm.cookies_file == Path("cookies/session.json")


# ─── start ────────────────────────────────────────────────────────────────────

class TestBrowserManagerStart:
    @pytest.mark.asyncio
    async def test_start_launches_browser(self):
        cfg = {"headless": True, "cookies_file": "/tmp/nocookies.json"}
        bm = BrowserManager(cfg)

        pw, browser, context, page = make_mock_playwright()
        with patch("src.utils.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=pw)
            result = await bm.start()

        pw.chromium.launch.assert_called_once()
        assert result == context

    @pytest.mark.asyncio
    async def test_start_with_proxy(self):
        cfg = {
            "headless": True,
            "cookies_file": "/tmp/nocookies.json",
            "proxy": {"enabled": True, "server": "http://proxy:8080"},
        }
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()

        with patch("src.utils.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=pw)
            await bm.start()

        call_kwargs = pw.chromium.launch.call_args[1]
        assert call_kwargs.get("proxy") == {"server": "http://proxy:8080"}

    @pytest.mark.asyncio
    async def test_start_loads_cookies_when_file_exists(self, tmp_path):
        cookies_file = tmp_path / "session.json"
        cookies = [{"name": "c_user", "value": "12345", "domain": ".facebook.com"}]
        cookies_file.write_text(json.dumps(cookies))

        cfg = {"headless": True, "cookies_file": str(cookies_file)}
        bm = BrowserManager(cfg)

        pw, browser, context, page = make_mock_playwright()
        with patch("src.utils.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=pw)
            await bm.start()

        context.add_cookies.assert_called_once_with(cookies)

    @pytest.mark.asyncio
    async def test_start_skips_cookies_when_no_file(self, tmp_path):
        cfg = {"headless": True, "cookies_file": str(tmp_path / "no_such_file.json")}
        bm = BrowserManager(cfg)

        pw, browser, context, page = make_mock_playwright()
        with patch("src.utils.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=pw)
            await bm.start()

        context.add_cookies.assert_not_called()


# ─── close ────────────────────────────────────────────────────────────────────

class TestBrowserManagerClose:
    @pytest.mark.asyncio
    async def test_close_saves_cookies_when_configured(self, tmp_path):
        cfg = {"headless": True, "save_session": True, "cookies_file": str(tmp_path / "session.json")}
        bm = BrowserManager(cfg)

        pw, browser, context, page = make_mock_playwright()
        bm._playwright = pw
        bm._browser = browser
        bm._context = context

        await bm.close()

        context.cookies.assert_called_once()
        context.close.assert_called_once()
        browser.close.assert_called_once()
        pw.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_skips_cookies_when_save_session_false(self, tmp_path):
        cfg = {"headless": True, "save_session": False, "cookies_file": str(tmp_path / "session.json")}
        bm = BrowserManager(cfg)

        pw, browser, context, page = make_mock_playwright()
        bm._playwright = pw
        bm._browser = browser
        bm._context = context

        await bm.close()

        context.cookies.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_safe_when_nothing_started(self):
        cfg = {"cookies_file": "/tmp/test.json"}
        bm = BrowserManager(cfg)
        # All internal vars are None
        await bm.close()  # Should not raise


# ─── async context manager ────────────────────────────────────────────────────

class TestBrowserManagerContextManager:
    @pytest.mark.asyncio
    async def test_aenter_calls_start(self):
        cfg = {"headless": True, "cookies_file": "/tmp/nocookies.json"}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()

        with patch("src.utils.browser.async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=pw)
            result = await bm.__aenter__()
        assert result is bm

    @pytest.mark.asyncio
    async def test_aexit_calls_close(self):
        cfg = {"cookies_file": "/tmp/test.json", "save_session": False}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()
        bm._playwright = pw
        bm._browser = browser
        bm._context = context

        await bm.__aexit__(None, None, None)
        context.close.assert_called_once()


# ─── new_page ─────────────────────────────────────────────────────────────────

class TestNewPage:
    @pytest.mark.asyncio
    async def test_new_page_returns_page(self):
        cfg = {"timeout": 30000, "cookies_file": "/tmp/nocookies.json"}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()
        bm._context = context

        result = await bm.new_page()
        context.new_page.assert_called_once()
        assert result == page
        page.set_default_timeout.assert_called_once_with(30000)


# ─── save_cookies / load_cookies ──────────────────────────────────────────────

class TestSaveLoadCookies:
    @pytest.mark.asyncio
    async def test_save_cookies_writes_file(self, tmp_path):
        cookies_file = tmp_path / "session.json"
        cfg = {"cookies_file": str(cookies_file)}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()
        bm._context = context

        await bm.save_cookies()

        assert cookies_file.exists()
        saved = json.loads(cookies_file.read_text())
        assert saved == [{"name": "c_user", "value": "12345"}]

    @pytest.mark.asyncio
    async def test_save_cookies_skips_when_no_context(self):
        cfg = {"cookies_file": "/tmp/cookies.json"}
        bm = BrowserManager(cfg)
        bm._context = None
        # Should not raise
        await bm.save_cookies()

    @pytest.mark.asyncio
    async def test_load_cookies_adds_cookies(self, tmp_path):
        cookies = [{"name": "c_user", "value": "123", "domain": ".facebook.com"}]
        cookies_file = tmp_path / "session.json"
        cookies_file.write_text(json.dumps(cookies))

        cfg = {"cookies_file": str(cookies_file)}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()
        bm._context = context

        await bm.load_cookies()
        context.add_cookies.assert_called_once_with(cookies)

    @pytest.mark.asyncio
    async def test_load_cookies_skips_when_no_file(self, tmp_path):
        cfg = {"cookies_file": str(tmp_path / "no_file.json")}
        bm = BrowserManager(cfg)
        pw, browser, context, page = make_mock_playwright()
        bm._context = context

        await bm.load_cookies()
        context.add_cookies.assert_not_called()


# ─── _apply_stealth ───────────────────────────────────────────────────────────

class TestApplyStealth:
    @pytest.mark.asyncio
    async def test_applies_stealth_script(self):
        cfg = {}
        bm = BrowserManager(cfg)
        context = AsyncMock()
        context.add_init_script = AsyncMock()
        await bm._apply_stealth(context)
        context.add_init_script.assert_called_once()
        script = context.add_init_script.call_args[0][0]
        assert "webdriver" in script
        assert "chrome" in script
