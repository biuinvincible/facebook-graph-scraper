"""
Ban/checkpoint detector.
Nhận biết các dạng block của Facebook và phản ứng phù hợp.
"""
import asyncio
from enum import Enum
from typing import Optional
from playwright.async_api import Page
from loguru import logger


class BanType(Enum):
    NONE = "none"
    CHECKPOINT = "checkpoint"        # "Confirm your identity"
    LOGIN_WALL = "login_wall"        # Bị đẩy về trang login
    RATE_LIMIT = "rate_limit"        # "You're doing that too often"
    CAPTCHA = "captcha"              # reCAPTCHA / FunCaptcha
    ACCOUNT_DISABLED = "disabled"   # Tài khoản bị vô hiệu hóa
    IP_BLOCK = "ip_block"            # IP bị chặn
    TEMP_BLOCK = "temp_block"        # Tạm thời bị chặn


# Fingerprints để nhận biết từng loại ban
BAN_SIGNATURES = {
    BanType.CHECKPOINT: [
        "confirm your identity",
        "xác nhận danh tính",
        "checkpoint",
        "suspicious activity",
        "hoạt động đáng ngờ",
        "we noticed unusual activity",
    ],
    BanType.RATE_LIMIT: [
        "you're doing that too often",
        "bạn đang làm điều đó quá thường xuyên",
        "please try again later",
        "vui lòng thử lại sau",
        "try again in a few minutes",
        "thử lại sau vài phút",
    ],
    BanType.CAPTCHA: [
        "captcha",
        "robot",
        "security check",
        "kiểm tra bảo mật",
        "verify you're human",
    ],
    BanType.ACCOUNT_DISABLED: [
        "your account has been disabled",
        "tài khoản của bạn đã bị vô hiệu hóa",
        "account disabled",
    ],
    BanType.IP_BLOCK: [
        "access denied",
        "403",
        "this page isn't available",
        "trang này không khả dụng",
    ],
    BanType.TEMP_BLOCK: [
        "temporarily blocked",
        "tạm thời bị chặn",
        "you've been blocked",
        "temporarily restricted",
        "bị hạn chế tạm thời",
    ],
}

# Các URL patterns của trang checkpoint/block
BLOCK_URL_PATTERNS = [
    "/checkpoint/",
    "/login/",
    "/challenge/",
    "/security/",
    "checkpoint?next",
    "login?next",
]


class BanDetector:
    def __init__(self):
        self._consecutive_blocks = 0
        self._total_bans = 0

    async def check(self, page: Page) -> BanType:
        """Kiểm tra trang hiện tại có bị block không"""
        try:
            url = page.url.lower()
            title = (await page.title()).lower()

            # Kiểm tra URL
            for pattern in BLOCK_URL_PATTERNS:
                if pattern in url:
                    ban = await self._identify_from_page(page, url, title)
                    if ban != BanType.NONE:
                        self._record_ban(ban)
                    return ban

            # Kiểm tra nội dung trang
            try:
                body_text = await page.evaluate("document.body.innerText.toLowerCase()")
            except Exception:
                body_text = title

            for ban_type, signatures in BAN_SIGNATURES.items():
                for sig in signatures:
                    if sig in body_text or sig in title:
                        self._record_ban(ban_type)
                        logger.warning(f"Ban detected: {ban_type.value} | Signature: '{sig}'")
                        return ban_type

        except Exception as e:
            logger.debug(f"Ban check error: {e}")

        self._consecutive_blocks = 0
        return BanType.NONE

    async def _identify_from_page(self, page: Page, url: str, title: str) -> BanType:
        if "/checkpoint/" in url:
            return BanType.CHECKPOINT
        if "/login/" in url or "login?next" in url:
            return BanType.LOGIN_WALL
        if "/challenge/" in url or "/security/" in url:
            return BanType.CAPTCHA
        return BanType.NONE

    def _record_ban(self, ban_type: BanType):
        self._consecutive_blocks += 1
        self._total_bans += 1
        logger.error(f"Ban #{self._total_bans} | Type: {ban_type.value} | Consecutive: {self._consecutive_blocks}")

    @property
    def is_hard_banned(self) -> bool:
        """True nếu bị ban nặng cần dừng hẳn"""
        return self._consecutive_blocks >= 3

    def reset_consecutive(self):
        self._consecutive_blocks = 0
