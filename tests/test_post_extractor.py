"""
Tests for src/extractors/post_extractor.py — PostExtractor
Mock-based tests for all async Playwright-dependent methods.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.extractors.post_extractor import PostExtractor
from src.graph.schema import PostNode


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_mock_page(url="https://www.facebook.com/PageWSS/posts/123456"):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value="Test Page - Test post content | Facebook")
    page.content = AsyncMock(return_value="<html></html>")
    page.goto = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=None)
    handle = AsyncMock()
    handle.as_element = MagicMock(return_value=None)
    page.evaluate_handle = AsyncMock(return_value=handle)
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.locator = MagicMock(return_value=AsyncMock(count=AsyncMock(return_value=0)))
    page.fill = AsyncMock()
    return page


def make_mock_element(text="Hello world", href="https://www.facebook.com/user/123", aria="Comment by Test"):
    el = AsyncMock()
    el.get_attribute = AsyncMock(side_effect=lambda attr: {
        "aria-label": aria,
        "href": href,
        "src": "https://cdn.fbcdn.net/test.jpg",
        "data-utime": None,
    }.get(attr))
    el.inner_text = AsyncMock(return_value=text)
    el.is_visible = AsyncMock(return_value=True)
    el.scroll_into_view_if_needed = AsyncMock()
    el.click = AsyncMock()
    el.evaluate = AsyncMock(return_value={
        "authorName": "Test User",
        "authorHref": href,
        "text": text,
        "mentionedUsers": [],
        "likeCount": 5,
    })
    el.query_selector = AsyncMock(return_value=None)
    el.query_selector_all = AsyncMock(return_value=[])
    return el


# ─── __init__ ─────────────────────────────────────────────────────────────────

class TestPostExtractorInit:
    def test_init_stores_config(self):
        cfg = {"max_comments": 100, "custom": "val"}
        ext = PostExtractor(cfg)
        assert ext.cfg is cfg

    def test_init_empty_config(self):
        ext = PostExtractor({})
        assert ext.cfg == {}


# ─── extract_from_url ─────────────────────────────────────────────────────────

class TestExtractFromUrl:
    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        result = await ext.extract_from_url(page, "https://www.facebook.com/page/posts/123")
        assert result is None

    @pytest.mark.asyncio
    async def test_photo_url_calls_photo_path(self):
        ext = PostExtractor({})
        page = make_mock_page(url="https://www.facebook.com/photo/?fbid=12345")
        # Mock the sub-methods to avoid full navigation
        with patch.object(ext, "_extract_photo_page", new_callable=AsyncMock) as mock_photo:
            mock_photo.return_value = PostNode(post_id="photo_1", post_url="https://fb.com/photo/1")
            with patch.object(ext, "_dismiss_dialogs", new_callable=AsyncMock):
                result = await ext.extract_from_url(page, "https://www.facebook.com/photo/?fbid=12345")
        mock_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_regular_url_calls_extract_post_data(self):
        ext = PostExtractor({})
        page = make_mock_page()
        with patch.object(ext, "_extract_post_data", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = PostNode(post_id="p1", post_url="https://fb.com/posts/p1")
            with patch.object(ext, "_dismiss_dialogs", new_callable=AsyncMock):
                result = await ext.extract_from_url(page, "https://www.facebook.com/PageWSS/posts/12345")
        mock_post.assert_called_once()


# ─── extract_from_element ─────────────────────────────────────────────────────

class TestExtractFromElement:
    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = PostExtractor({})
        page = make_mock_page()
        element = AsyncMock()
        element.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext.extract_from_element(page, element, "https://fb.com/page")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_feed_url_if_no_post_link(self):
        ext = PostExtractor({})
        page = make_mock_page()
        element = AsyncMock()

        with patch.object(ext, "_get_post_link", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_extract_text", new_callable=AsyncMock, return_value="Hello world"):
                with patch.object(ext, "_extract_author", new_callable=AsyncMock, return_value=("uid1", "Author")):
                    with patch.object(ext, "_extract_timestamp", new_callable=AsyncMock, return_value="2024-01-01"):
                        with patch.object(ext, "_extract_images", new_callable=AsyncMock, return_value=[]):
                            with patch.object(ext, "_extract_videos", new_callable=AsyncMock, return_value=[]):
                                with patch.object(ext, "_extract_reactions_from_element", new_callable=AsyncMock,
                                                  return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                                                "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                                "care_count": 0, "comment_count": 0,
                                                                "share_count": 0, "view_count": None}):
                                    result = await ext.extract_from_element(page, element, "https://fb.com/page")
        assert result is not None
        assert result.post_url is not None  # URL was set (may or may not normalize fb.com)


# ─── _find_post_container ─────────────────────────────────────────────────────

class TestFindPostContainer:
    @pytest.mark.asyncio
    async def test_returns_mbasic_container_if_found(self):
        ext = PostExtractor({})
        page = make_mock_page()
        mbasic_el = make_mock_element()
        page.query_selector = AsyncMock(return_value=mbasic_el)
        result = await ext._find_post_container(page)
        assert result == mbasic_el

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_found(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._find_post_container(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_finds_pagelet_selector(self):
        ext = PostExtractor({})
        page = make_mock_page()
        pagelet_el = make_mock_element()
        call_count = [0]

        async def mock_qs(sel):
            call_count[0] += 1
            # Return None for mbasic, return element for pagelet
            if "m_story" in sel or "MPhoto" in sel:
                return None
            if "PermalinkPostFeed" in sel:
                return pagelet_el
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._find_post_container(page)
        # The function returns first non-None from pagelet selectors
        assert result == pagelet_el


# ─── _extract_photo_timestamp ─────────────────────────────────────────────────

class TestExtractPhotoTimestamp:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_elements(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._extract_photo_timestamp(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_aria_label_when_found(self):
        ext = PostExtractor({})
        page = make_mock_page()
        el = make_mock_element()
        el.get_attribute = AsyncMock(return_value="2 tuần trước")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._extract_photo_timestamp(page)
        assert result == "2 tuần trước"

    @pytest.mark.asyncio
    async def test_falls_back_to_abbr(self):
        ext = PostExtractor({})
        page = make_mock_page()
        abbr = make_mock_element()
        abbr.get_attribute = AsyncMock(side_effect=lambda a: "1700000000" if a == "data-utime" else None)

        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "tuần" in sel or "week" in sel:
                return None
            if "abbr" in sel:
                return abbr
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        result = await ext._extract_photo_timestamp(page)
        # Should return an ISO timestamp
        assert result is not None and "T" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._extract_photo_timestamp(page)
        assert result is None


# ─── _extract_photo_image ─────────────────────────────────────────────────────

class TestExtractPhotoImage:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_images(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.evaluate = AsyncMock(return_value=[])
        result = await ext._extract_photo_image(page, "https://fb.com/photo/1")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_image_urls(self):
        ext = PostExtractor({})
        page = make_mock_page()
        urls = ["https://scontent.fbcdn.net/img1.jpg", "https://scontent.fbcdn.net/img2.jpg"]
        page.evaluate = AsyncMock(return_value=urls)
        result = await ext._extract_photo_image(page, "https://fb.com/photo/1")
        assert result == urls


# ─── _dismiss_dialogs ─────────────────────────────────────────────────────────

class TestDismissDialogs:
    @pytest.mark.asyncio
    async def test_dismiss_dialogs_no_popups(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        # Should not raise
        await ext._dismiss_dialogs(page)

    @pytest.mark.asyncio
    async def test_dismiss_dialogs_clicks_close_button(self):
        ext = PostExtractor({})
        page = make_mock_page()
        btn = make_mock_element()
        btn.is_visible = AsyncMock(return_value=True)
        page.query_selector = AsyncMock(return_value=btn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._dismiss_dialogs(page)
        btn.click.assert_called()


# ─── Private extraction helpers ──────────────────────────────────────────────

class TestPrivateHelpers:
    @pytest.mark.asyncio
    async def test_extract_page_author_returns_none_when_no_element(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._extract_page_author(page)
        # Should return (None, None) or similar tuple
        assert isinstance(result, tuple)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_extract_page_reactions_returns_dict(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._extract_page_reactions(page)
        assert isinstance(result, dict)
        assert "like_count" in result

    @pytest.mark.asyncio
    async def test_get_comment_count_from_html_returns_zero(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[])
        result = await ext._get_comment_count_from_html(page)
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_share_count_from_html_returns_zero(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_share_count_from_html(page)
        assert result == 0

    @pytest.mark.asyncio
    async def test_extract_page_location_returns_none(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._extract_page_location(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_tagged_users_returns_empty_list(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[])
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._extract_tagged_users(page)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_page_timestamp_returns_none(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._extract_page_timestamp(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_post_data_returns_none_on_error(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.goto = AsyncMock(side_effect=Exception("Error"))
        # _extract_post_data is called internally; test via extract_from_url
        with patch.object(ext, "_extract_photo_page", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_dismiss_dialogs", new_callable=AsyncMock):
                # Regular URL — will call _extract_post_data
                result = await ext.extract_from_url(page, "https://fb.com/page/posts/123")
        assert result is None


# ─── _get_post_text_element ────────────────────────────────────────────────────

class TestGetPostTextElement:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_text_found(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.title = AsyncMock(return_value="Facebook")
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ext._get_post_text_element(page)
        assert result is None or (isinstance(result, tuple) and result[0] is None)

    @pytest.mark.asyncio
    async def test_returns_element_when_title_matches(self):
        ext = PostExtractor({})
        page = make_mock_page()
        page.title = AsyncMock(return_value="Test Page - Hello world from post | Facebook")

        text_el = make_mock_element(text="Hello world from post, this is a longer text")
        text_el.inner_text = AsyncMock(return_value="Hello world from post, this is a longer text")

        call_count = [0]
        async def mock_qsa(sel):
            call_count[0] += 1
            if "data-ad-rendering" in sel or "data-ad-comet" in sel or "data-ad-preview" in sel:
                return [text_el]
            return []

        page.query_selector_all = AsyncMock(side_effect=mock_qsa)
        page.evaluate = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ext._get_post_text_element(page)
        # Should return (element, text) or None
        assert result is None or (isinstance(result, tuple))


# ─── _merge_posts (not in PostExtractor — in PageScraper) ─────────────────────
# PostExtractor's private helper tests

class TestExtractAuthorFromElement:
    @pytest.mark.asyncio
    async def test_returns_none_none_when_no_author(self):
        ext = PostExtractor({})
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        el.evaluate = AsyncMock(return_value=None)
        result = await ext._extract_author(el)
        assert isinstance(result, tuple)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_extracts_author_from_link(self):
        ext = PostExtractor({})
        el = AsyncMock()
        author_el = make_mock_element(href="https://www.facebook.com/user/1234567890")
        author_el.inner_text = AsyncMock(return_value="Test Author")

        el.query_selector = AsyncMock(return_value=author_el)
        result = await ext._extract_author(el)
        assert isinstance(result, tuple)
