"""
User/Profile extractor - builds UserNode from Facebook profile/page.
"""
import asyncio
from typing import Optional, Dict, Any, Tuple
from playwright.async_api import Page
from loguru import logger

from ..graph.schema import UserNode
from ..utils.helpers import extract_user_id, parse_count, clean_text


class UserExtractor:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config

    async def extract_from_url(self, page: Page, profile_url: str) -> Optional[UserNode]:
        """Navigate to profile and extract user data"""
        try:
            await page.goto(profile_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            return await self._extract(page, profile_url)
        except Exception as e:
            logger.error(f"Failed to extract user from {profile_url}: {e}")
            return None

    async def extract_from_name(self, page: Page, user_id: str, display_name: str) -> UserNode:
        """Create minimal UserNode from known ID and name"""
        return UserNode(
            user_id=user_id,
            display_name=display_name,
            profile_url=f"https://www.facebook.com/{user_id}" if user_id else None,
        )

    async def _extract(self, page: Page, url: str) -> Optional[UserNode]:
        user_id = extract_user_id(url) or "unknown"

        # Display name
        display_name = await self._get_display_name(page)

        # Bio
        bio = await self._get_bio(page)

        # Profile image
        profile_img = await self._get_profile_image(page)

        # Stats
        follower_count = await self._get_follower_count(page)
        friend_count = await self._get_friend_count(page)
        is_verified = await self._get_is_verified(page)
        is_page = "pages" in url or await self._is_page(page)
        location = await self._get_location(page)

        return UserNode(
            user_id=user_id,
            profile_url=url,
            display_name=display_name,
            bio_text=bio,
            profile_image_url=profile_img,
            follower_count=follower_count,
            friend_count=friend_count,
            is_verified=is_verified,
            is_page=is_page,
            location=location,
        )

    async def _get_display_name(self, page: Page) -> Optional[str]:
        selectors = [
            "h1",
            '[data-testid="profile_name_in_profile_page"]',
            'span[dir="auto"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    name = (await el.inner_text()).strip()
                    if name and len(name) > 1:
                        return name
            except Exception:
                continue
        return None

    async def _get_bio(self, page: Page) -> Optional[str]:
        selectors = [
            '[data-testid="profile_intro_card"] div[dir="auto"]',
            'div[class*="bio"] span',
            'div[data-overridetype="bio"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return clean_text(text)
            except Exception:
                continue
        return None

    async def _get_profile_image(self, page: Page) -> Optional[str]:
        try:
            img = await page.query_selector(
                'image[xlink\\:href*="fbcdn.net"], '
                'img[data-imgperflogname="profileCoverPhoto"]'
            )
            if not img:
                img = await page.query_selector('svg > image')
            if img:
                href = await img.get_attribute("xlink:href") or await img.get_attribute("src")
                return href
        except Exception:
            pass
        return None

    async def _get_follower_count(self, page: Page) -> Optional[int]:
        selectors = [
            'a[href*="followers"] span',
            '[data-testid="profile_followers_count"]',
            'div:has-text("followers") span',
            'div:has-text("người theo dõi")',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    count = parse_count(text.split()[0])
                    if count > 0:
                        return count
            except Exception:
                continue
        return None

    async def _get_friend_count(self, page: Page) -> Optional[int]:
        try:
            el = await page.query_selector(
                'a[href*="friends"] div:has-text("friend")'
            )
            if el:
                text = (await el.inner_text()).strip()
                return parse_count(text.split()[0])
        except Exception:
            pass
        return None

    async def _get_is_verified(self, page: Page) -> bool:
        try:
            badge = await page.query_selector(
                '[aria-label="Verified account"], '
                '[data-testid="profile_verified_badge"], '
                'svg[aria-label*="erified"]'
            )
            return badge is not None
        except Exception:
            return False

    async def _is_page(self, page: Page) -> bool:
        try:
            el = await page.query_selector(
                'div[data-pagelet="ProfileTilesFeed"], '
                '[data-testid="page-info-section"]'
            )
            return el is not None
        except Exception:
            return False

    async def _get_location(self, page: Page) -> Optional[str]:
        try:
            el = await page.query_selector(
                'div[data-overridetype="city"] span, '
                'span[dir="auto"]:has-text("Lives in"), '
                'span:has-text("Sống tại")'
            )
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            pass
        return None
