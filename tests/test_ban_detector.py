"""
Tests for src/utils/ban_detector.py — BanDetector + BanType
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.ban_detector import BanDetector, BanType


def make_page(url="https://www.facebook.com/page", title="Facebook", body_text=""):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.evaluate = AsyncMock(return_value=body_text)
    return page


class TestBanDetectorInit:
    def test_initial_state(self):
        bd = BanDetector()
        assert bd._consecutive_blocks == 0
        assert bd._total_bans == 0
        assert not bd.is_hard_banned

    def test_reset_consecutive(self):
        bd = BanDetector()
        bd._consecutive_blocks = 5
        bd.reset_consecutive()
        assert bd._consecutive_blocks == 0


class TestBanDetectorNone:
    @pytest.mark.asyncio
    async def test_no_ban_normal_page(self):
        page = make_page(
            url="https://www.facebook.com/PageWSS/posts/12345",
            title="PageWSS",
            body_text="some regular content here",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.NONE

    @pytest.mark.asyncio
    async def test_no_ban_resets_consecutive(self):
        page = make_page(body_text="normal content")
        bd = BanDetector()
        bd._consecutive_blocks = 2
        result = await bd.check(page)
        assert result == BanType.NONE
        assert bd._consecutive_blocks == 0


class TestBanDetectorCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_url_detected(self):
        page = make_page(
            url="https://www.facebook.com/checkpoint/?next=...",
            title="Security Check",
            body_text="confirm your identity",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.CHECKPOINT

    @pytest.mark.asyncio
    async def test_checkpoint_via_body_text(self):
        page = make_page(
            url="https://www.facebook.com/some/normal/page",
            body_text="confirm your identity to continue",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.CHECKPOINT


class TestBanDetectorLoginWall:
    @pytest.mark.asyncio
    async def test_login_wall_url_detected(self):
        page = make_page(
            url="https://www.facebook.com/login/?next=...",
            title="Log In",
            body_text="",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.LOGIN_WALL

    @pytest.mark.asyncio
    async def test_login_next_url(self):
        page = make_page(
            url="https://www.facebook.com/login?next=https%3A%2F%2Fwww.facebook.com%2Fpage",
            body_text="",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.LOGIN_WALL


class TestBanDetectorCaptcha:
    @pytest.mark.asyncio
    async def test_challenge_url_detected(self):
        page = make_page(
            url="https://www.facebook.com/challenge/?foo=bar",
            body_text="security check",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.CAPTCHA

    @pytest.mark.asyncio
    async def test_security_url_detected(self):
        # /security/checkpoint/ matches /checkpoint/ first → CHECKPOINT (not CAPTCHA)
        # A pure /security/ URL without /checkpoint/ would return CAPTCHA
        page = make_page(
            url="https://www.facebook.com/security/?ref=foo",
            body_text="",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.CAPTCHA

    @pytest.mark.asyncio
    async def test_captcha_body_text(self):
        page = make_page(
            url="https://www.facebook.com/some/page",
            body_text="captcha required to continue",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.CAPTCHA


class TestBanDetectorRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_detected_from_body(self):
        page = make_page(
            url="https://www.facebook.com/page",
            body_text="you're doing that too often",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.RATE_LIMIT

    @pytest.mark.asyncio
    async def test_please_try_again_later(self):
        page = make_page(body_text="please try again later to continue")
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.RATE_LIMIT


class TestBanDetectorAccountDisabled:
    @pytest.mark.asyncio
    async def test_account_disabled_body(self):
        page = make_page(
            body_text="your account has been disabled by facebook",
        )
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.ACCOUNT_DISABLED


class TestBanDetectorTempBlock:
    @pytest.mark.asyncio
    async def test_temp_block_body(self):
        page = make_page(body_text="you've been temporarily blocked from doing this")
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.TEMP_BLOCK

    @pytest.mark.asyncio
    async def test_temporarily_restricted_body(self):
        page = make_page(body_text="temporarily restricted some actions")
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.TEMP_BLOCK


class TestBanDetectorIPBlock:
    @pytest.mark.asyncio
    async def test_ip_block_access_denied_body(self):
        page = make_page(body_text="access denied to this content")
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.IP_BLOCK


class TestBanDetectorRecordBan:
    @pytest.mark.asyncio
    async def test_consecutive_blocks_increment(self):
        page = make_page(body_text="confirm your identity")
        bd = BanDetector()
        await bd.check(page)
        assert bd._consecutive_blocks == 1
        assert bd._total_bans == 1

    @pytest.mark.asyncio
    async def test_is_hard_banned_after_3(self):
        page = make_page(body_text="confirm your identity")
        bd = BanDetector()
        for _ in range(3):
            await bd.check(page)
        assert bd.is_hard_banned

    @pytest.mark.asyncio
    async def test_not_hard_banned_before_3(self):
        page = make_page(body_text="confirm your identity")
        bd = BanDetector()
        for _ in range(2):
            await bd.check(page)
        assert not bd.is_hard_banned


class TestBanDetectorErrorHandling:
    @pytest.mark.asyncio
    async def test_evaluate_exception_falls_back_to_title(self):
        page = AsyncMock()
        page.url = "https://www.facebook.com/normal"
        page.title = AsyncMock(return_value="normal page")
        page.evaluate = AsyncMock(side_effect=Exception("JS error"))
        bd = BanDetector()
        result = await bd.check(page)
        assert result == BanType.NONE

    @pytest.mark.asyncio
    async def test_page_error_returns_none(self):
        page = AsyncMock()
        page.url = "https://www.facebook.com/normal"
        page.title = AsyncMock(side_effect=Exception("page crashed"))
        bd = BanDetector()
        result = await bd.check(page)
        # Should not raise, returns NONE (exception swallowed)
        assert result == BanType.NONE


class TestIdentifyFromPage:
    @pytest.mark.asyncio
    async def test_identify_checkpoint(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "/checkpoint/foo", "title")
        assert result == BanType.CHECKPOINT

    @pytest.mark.asyncio
    async def test_identify_login(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "/login/", "title")
        assert result == BanType.LOGIN_WALL

    @pytest.mark.asyncio
    async def test_identify_login_next(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "login?next=foo", "title")
        assert result == BanType.LOGIN_WALL

    @pytest.mark.asyncio
    async def test_identify_challenge(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "/challenge/", "title")
        assert result == BanType.CAPTCHA

    @pytest.mark.asyncio
    async def test_identify_security(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "/security/", "title")
        assert result == BanType.CAPTCHA

    @pytest.mark.asyncio
    async def test_identify_none_for_unknown(self):
        bd = BanDetector()
        page = AsyncMock()
        result = await bd._identify_from_page(page, "/some/other/url", "title")
        assert result == BanType.NONE
