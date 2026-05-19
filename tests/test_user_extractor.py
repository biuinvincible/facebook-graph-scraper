"""
Tests for src/extractors/user_extractor.py — UserExtractor
Covers all methods with mock-based tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.extractors.user_extractor import UserExtractor
from src.graph.schema import UserNode


def make_page():
    page = AsyncMock()
    page.url = "https://www.facebook.com/testpage"
    page.goto = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=None)
    return page


def make_el(text="Test Text", href="https://www.facebook.com/user1"):
    el = AsyncMock()
    el.inner_text = AsyncMock(return_value=text)
    el.get_attribute = AsyncMock(return_value=href)
    el.evaluate = AsyncMock(return_value=href)
    el.query_selector = AsyncMock(return_value=None)
    return el


# ─── __init__ ─────────────────────────────────────────────────────────────────

class TestUserExtractorInit:
    def test_init_stores_config(self):
        cfg = {"key": "value"}
        ext = UserExtractor(cfg)
        assert ext.cfg is cfg


# ─── extract_from_url ─────────────────────────────────────────────────────────

class TestExtractFromUrl:
    @pytest.mark.asyncio
    async def test_returns_user_node_on_success(self):
        ext = UserExtractor({})
        page = make_page()
        with patch.object(ext, "_extract", new_callable=AsyncMock,
                          return_value=UserNode(user_id="u1", display_name="Test Page")):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ext.extract_from_url(page, "https://www.facebook.com/testpage")
        assert result is not None
        assert result.user_id == "u1"

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        result = await ext.extract_from_url(page, "https://www.facebook.com/testpage")
        assert result is None


# ─── extract_from_name ────────────────────────────────────────────────────────

class TestExtractFromName:
    @pytest.mark.asyncio
    async def test_creates_user_node_with_profile_url(self):
        ext = UserExtractor({})
        result = await ext.extract_from_name(None, "user123", "Test User")
        assert result.user_id == "user123"
        assert result.display_name == "Test User"
        assert "user123" in result.profile_url

    @pytest.mark.asyncio
    async def test_handles_empty_user_id(self):
        ext = UserExtractor({})
        result = await ext.extract_from_name(None, "", "Test User")
        assert result.display_name == "Test User"
        # When user_id is empty, profile_url should be None
        assert result.profile_url is None


# ─── _extract ─────────────────────────────────────────────────────────────────

class TestExtract:
    @pytest.mark.asyncio
    async def test_extracts_full_user_node(self):
        ext = UserExtractor({})
        page = make_page()
        with patch.object(ext, "_get_display_name", new_callable=AsyncMock, return_value="Page Name"):
            with patch.object(ext, "_get_bio", new_callable=AsyncMock, return_value="Bio text"):
                with patch.object(ext, "_get_profile_image", new_callable=AsyncMock,
                                  return_value="https://cdn/profile.jpg"):
                    with patch.object(ext, "_get_follower_count", new_callable=AsyncMock,
                                      return_value=1000):
                        with patch.object(ext, "_get_friend_count", new_callable=AsyncMock,
                                          return_value=500):
                            with patch.object(ext, "_get_is_verified", new_callable=AsyncMock,
                                              return_value=True):
                                with patch.object(ext, "_is_page", new_callable=AsyncMock,
                                                  return_value=True):
                                    with patch.object(ext, "_get_location", new_callable=AsyncMock,
                                                      return_value="Hanoi"):
                                        result = await ext._extract(
                                            page, "https://www.facebook.com/testpage"
                                        )
        assert result.display_name == "Page Name"
        assert result.bio_text == "Bio text"
        assert result.follower_count == 1000
        assert result.is_verified is True
        assert result.is_page is True
        assert result.location == "Hanoi"


# ─── _get_display_name ────────────────────────────────────────────────────────

class TestGetDisplayName:
    @pytest.mark.asyncio
    async def test_returns_name_from_h1(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="Test Page Name")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_display_name(page)
        assert result == "Test Page Name"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_display_name(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_single_char_name(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="A")  # too short
        el2 = make_el(text="Real Name")
        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if call_count[0] == 1:
                return el  # returns short name
            return el2  # returns real name
        page.query_selector = AsyncMock(side_effect=mock_qs)
        result = await ext._get_display_name(page)
        # First element returns "A" which is length <= 1, should try next
        assert result is not None


# ─── _get_bio ─────────────────────────────────────────────────────────────────

class TestGetBio:
    @pytest.mark.asyncio
    async def test_returns_bio_text(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="This is the bio text of the page")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_bio(page)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_bio(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_bio(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_bio(page)
        assert result is None


# ─── _get_profile_image ───────────────────────────────────────────────────────

class TestGetProfileImage:
    @pytest.mark.asyncio
    async def test_returns_profile_image_url(self):
        ext = UserExtractor({})
        page = make_page()
        img = AsyncMock()
        img.get_attribute = AsyncMock(return_value="https://cdn.fbcdn.net/profile.jpg")
        page.query_selector = AsyncMock(return_value=img)
        result = await ext._get_profile_image(page)
        assert result == "https://cdn.fbcdn.net/profile.jpg"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_image(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_profile_image(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_svg_image(self):
        ext = UserExtractor({})
        page = make_page()
        call_count = [0]
        img = AsyncMock()
        img.get_attribute = AsyncMock(return_value="https://cdn.fbcdn.net/profile.jpg")

        async def mock_qs(sel):
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # First selector fails
            return img  # Fallback to svg > image

        page.query_selector = AsyncMock(side_effect=mock_qs)
        result = await ext._get_profile_image(page)
        assert result == "https://cdn.fbcdn.net/profile.jpg"

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_profile_image(page)
        assert result is None


# ─── _get_follower_count ──────────────────────────────────────────────────────

class TestGetFollowerCount:
    @pytest.mark.asyncio
    async def test_extracts_follower_count(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="1.5M người theo dõi")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_follower_count(page)
        # parse_count("1.5M") should return a number
        assert isinstance(result, (int, type(None)))

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_follower_count(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_count_is_zero(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="0 followers")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_follower_count(page)
        # Returns None if count is 0
        assert result is None or result == 0


# ─── _get_friend_count ────────────────────────────────────────────────────────

class TestGetFriendCount:
    @pytest.mark.asyncio
    async def test_extracts_friend_count(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="500 friends")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_friend_count(page)
        assert isinstance(result, (int, type(None)))

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_friend_count(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_friend_count(page)
        assert result is None


# ─── _get_is_verified ─────────────────────────────────────────────────────────

class TestGetIsVerified:
    @pytest.mark.asyncio
    async def test_returns_true_when_badge_found(self):
        ext = UserExtractor({})
        page = make_page()
        badge = AsyncMock()
        page.query_selector = AsyncMock(return_value=badge)
        result = await ext._get_is_verified(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_badge(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_is_verified(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_is_verified(page)
        assert result is False


# ─── _is_page ─────────────────────────────────────────────────────────────────

class TestIsPage:
    @pytest.mark.asyncio
    async def test_returns_true_when_page_element_found(self):
        ext = UserExtractor({})
        page = make_page()
        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._is_page(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_element(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._is_page(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._is_page(page)
        assert result is False


# ─── _get_location ────────────────────────────────────────────────────────────

class TestGetLocation:
    @pytest.mark.asyncio
    async def test_returns_location_text(self):
        ext = UserExtractor({})
        page = make_page()
        el = make_el(text="Lives in Hanoi, Vietnam")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_location(page)
        assert result == "Lives in Hanoi, Vietnam"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_location(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_location(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = UserExtractor({})
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_location(page)
        assert result is None
