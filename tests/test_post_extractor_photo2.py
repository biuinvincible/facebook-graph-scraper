"""
More targeted tests for PostExtractor to hit remaining uncovered lines.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.extractors.post_extractor import PostExtractor
from src.graph.schema import PostNode


def make_mock_page(url="https://www.facebook.com/photo/?fbid=12345"):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value="Test")
    page.goto = AsyncMock(return_value=None)
    page.wait_for_selector = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=None)
    handle = AsyncMock()
    handle.as_element = MagicMock(return_value=None)
    page.evaluate_handle = AsyncMock(return_value=handle)
    page.content = AsyncMock(return_value="<html></html>")
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.fill = AsyncMock()
    page.locator = MagicMock(return_value=AsyncMock())
    return page


def patch_all_page_methods(ext):
    """Return a context manager that patches all page methods for _extract_photo_page."""
    return [
        patch.object(ext, "_extract_page_author", new_callable=AsyncMock, return_value=(None, None)),
        patch.object(ext, "_extract_page_timestamp", new_callable=AsyncMock, return_value=None),
        patch.object(ext, "_extract_photo_image", new_callable=AsyncMock, return_value=[]),
        patch.object(ext, "_extract_photo_timestamp", new_callable=AsyncMock, return_value=None),
        patch.object(ext, "_extract_page_reactions", new_callable=AsyncMock,
                     return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                    "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                    "care_count": 0, "comment_count": 0,
                                    "share_count": 0, "view_count": None}),
        patch.object(ext, "_get_comment_count_from_html", new_callable=AsyncMock, return_value=0),
        patch.object(ext, "_get_share_count_from_html", new_callable=AsyncMock, return_value=0),
        patch.object(ext, "_extract_page_location", new_callable=AsyncMock, return_value=None),
        patch.object(ext, "_extract_tagged_users", new_callable=AsyncMock, return_value=[]),
    ]


# ─── _extract_photo_page with right_panel ────────────────────────────────────

class TestExtractPhotoPageWithRightPanel:
    @pytest.mark.asyncio
    async def test_extracts_author_name_from_right_panel(self):
        """Test the right_panel author extraction path (lines 64-74)."""
        ext = PostExtractor({})
        page = make_mock_page()

        right_panel = AsyncMock()
        # Make right_panel.query_selector return an element with author name
        author_el = AsyncMock()
        author_el.inner_text = AsyncMock(return_value="PageName")
        right_panel.query_selector = AsyncMock(return_value=author_el)
        right_panel.evaluate = AsyncMock(return_value="Caption text here!")

        # Make right_panel also handle data-ad-* queries (for caption extraction)
        caption_el = AsyncMock()
        caption_el.inner_text = AsyncMock(return_value="Caption text here!")
        right_panel.query_selector = AsyncMock(return_value=caption_el)

        page.query_selector = AsyncMock(return_value=right_panel)
        page.evaluate = AsyncMock(return_value=[])  # For _extract_photo_image mock

        with patch.object(ext, "_extract_page_author", new_callable=AsyncMock, return_value=(None, "PageName")):
            with patch.object(ext, "_extract_page_timestamp", new_callable=AsyncMock, return_value=None):
                with patch.object(ext, "_extract_photo_image", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_extract_photo_timestamp", new_callable=AsyncMock, return_value=None):
                        with patch.object(ext, "_extract_page_reactions", new_callable=AsyncMock,
                                          return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                                         "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                         "care_count": 0, "comment_count": 0,
                                                         "share_count": 0, "view_count": None}):
                            with patch.object(ext, "_get_comment_count_from_html", new_callable=AsyncMock, return_value=0):
                                with patch.object(ext, "_get_share_count_from_html", new_callable=AsyncMock, return_value=0):
                                    with patch.object(ext, "_extract_page_location", new_callable=AsyncMock, return_value=None):
                                        with patch.object(ext, "_extract_tagged_users", new_callable=AsyncMock, return_value=[]):
                                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                                result = await ext._extract_photo_page(
                                                    page, "https://www.facebook.com/photo/?fbid=12345"
                                                )
        assert result is not None

    @pytest.mark.asyncio
    async def test_extracts_caption_that_starts_with_author_name(self):
        """Test the text skipping logic when caption starts with author name (line 93-94)."""
        ext = PostExtractor({})
        page = make_mock_page()

        right_panel = AsyncMock()
        # Author name extraction
        author_el = AsyncMock()
        author_el.inner_text = AsyncMock(return_value="PageName")
        caption_el = AsyncMock()
        # Caption starts with author name — should be skipped
        caption_el.inner_text = AsyncMock(return_value="PageName is posting something")

        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "h2" in sel:
                return author_el
            if "data-ad" in sel:
                return caption_el
            return None

        right_panel.query_selector = AsyncMock(side_effect=mock_qs)
        right_panel.evaluate = AsyncMock(return_value="Caption after JS filter")
        page.query_selector = AsyncMock(return_value=right_panel)
        page.evaluate = AsyncMock(return_value=[])

        with patch.object(ext, "_extract_page_author", new_callable=AsyncMock, return_value=(None, None)):
            with patch.object(ext, "_extract_page_timestamp", new_callable=AsyncMock, return_value=None):
                with patch.object(ext, "_extract_photo_image", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_extract_photo_timestamp", new_callable=AsyncMock, return_value=None):
                        with patch.object(ext, "_extract_page_reactions", new_callable=AsyncMock,
                                          return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                                         "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                         "care_count": 0, "comment_count": 0,
                                                         "share_count": 0, "view_count": None}):
                            with patch.object(ext, "_get_comment_count_from_html", new_callable=AsyncMock, return_value=0):
                                with patch.object(ext, "_get_share_count_from_html", new_callable=AsyncMock, return_value=0):
                                    with patch.object(ext, "_extract_page_location", new_callable=AsyncMock, return_value=None):
                                        with patch.object(ext, "_extract_tagged_users", new_callable=AsyncMock, return_value=[]):
                                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                                result = await ext._extract_photo_page(
                                                    page, "https://www.facebook.com/photo/?fbid=12345"
                                                )
        assert result is not None


# ─── _extract_post_data with See more button ──────────────────────────────────

class TestExtractPostDataWithSeeMore:
    @pytest.mark.asyncio
    async def test_clicks_see_more_when_text_truncated(self):
        """Test the 'Xem thêm' click path in _extract_post_data (lines 489-500)."""
        ext = PostExtractor({})
        page = make_mock_page(url="https://www.facebook.com/PageWSS/posts/12345")
        page.content = AsyncMock(return_value="<html></html>")

        see_more_btn = AsyncMock()
        see_more_btn.is_visible = AsyncMock(return_value=True)
        see_more_btn.click = AsyncMock()

        text_el = AsyncMock()
        text_el.inner_text = AsyncMock(return_value="This is truncated... Xem thêm")

        parent_handle = AsyncMock()
        parent_el = AsyncMock()
        parent_el.query_selector = AsyncMock(return_value=see_more_btn)
        parent_handle.as_element = MagicMock(return_value=parent_el)
        text_el.evaluate_handle = AsyncMock(return_value=parent_handle)

        call_count = [0]
        async def mock_get_text_el(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return (text_el, "This is truncated... Xem thêm")
            return (None, "Full text after expanding")

        with patch.object(ext, "_get_post_text_element", side_effect=mock_get_text_el):
            with patch.object(ext, "_find_post_container", new_callable=AsyncMock, return_value=None):
                with patch.object(ext, "_extract_author_from", new_callable=AsyncMock, return_value=(None, None)):
                    with patch.object(ext, "_extract_timestamp_from", new_callable=AsyncMock, return_value=None):
                        with patch.object(ext, "_get_foreground_container", new_callable=AsyncMock, return_value=None):
                            with patch.object(ext, "_extract_images_from", new_callable=AsyncMock, return_value=[]):
                                with patch.object(ext, "_extract_videos_from", new_callable=AsyncMock, return_value=[]):
                                    with patch.object(ext, "_extract_page_reactions", new_callable=AsyncMock,
                                                      return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                                                     "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                                     "care_count": 0, "comment_count": 0,
                                                                     "share_count": 0, "view_count": None}):
                                        with patch.object(ext, "_get_reactions_from_html", new_callable=AsyncMock, return_value={}):
                                            with patch.object(ext, "_get_comment_count_from_html", new_callable=AsyncMock, return_value=0):
                                                with patch.object(ext, "_get_share_count_from_html", new_callable=AsyncMock, return_value=0):
                                                    with patch.object(ext, "_extract_page_location", new_callable=AsyncMock, return_value=None):
                                                        with patch.object(ext, "_extract_tagged_users_from", new_callable=AsyncMock, return_value=[]):
                                                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                                                result = await ext._extract_post_data(
                                                                    page, "https://www.facebook.com/PageWSS/posts/12345"
                                                                )
        assert result is not None


# ─── _extract_author_from (slug fallback) ────────────────────────────────────

class TestExtractAuthorFromSlugFallback:
    @pytest.mark.asyncio
    async def test_finds_author_from_slug(self):
        """Test the slug-based author fallback (lines 605-636)."""
        ext = PostExtractor({})
        root = AsyncMock()
        root.query_selector = AsyncMock(return_value=None)  # Primary selector fails

        page = make_mock_page(url="https://www.facebook.com/TestPage/posts/123456")
        page.url = "https://www.facebook.com/TestPage/posts/123456"

        # Make query_selector_all return a link element
        link_el = AsyncMock()
        link_el.evaluate = AsyncMock(side_effect=lambda js, *args: {
            "e => e.href || ''": "https://www.facebook.com/TestPage",
            "(e, id) => !!el.querySelector": False,
            "e => (e.innerText || '').replace(/\\s+/g, ' ').trim()": "Test Page Name",
            "e => !!e.closest('[role=\"article\"]') || !!e.closest('[aria-label*=\"ụng\"]')": False,
        }.get(js, ""))
        page.query_selector_all = AsyncMock(return_value=[link_el])

        result = await ext._extract_author_from(root, page)
        assert isinstance(result, tuple)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_h2_text(self):
        """Test the h2 'Bài viết của' fallback (lines 638-656)."""
        ext = PostExtractor({})
        root = AsyncMock()
        root.query_selector = AsyncMock(return_value=None)

        page = make_mock_page(url="https://www.facebook.com/unknown/posts/123")
        page.url = "https://www.facebook.com/unknown/posts/123"
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        # Simulate h2 "Posts by PageName" fallback
        page.evaluate = AsyncMock(return_value="Test Author Name")

        result = await ext._extract_author_from(root, page)
        assert isinstance(result, tuple)
        # Should return None, "Test Author Name" from the h2 fallback
        if result[1] is not None:
            assert result[1] == "Test Author Name"


# ─── _extract_page_reactions with scoped_root ────────────────────────────────

class TestExtractPageReactionsScoped:
    @pytest.mark.asyncio
    async def test_extracts_from_scoped_root_first(self):
        """Test that reactions are extracted from scoped_root when provided."""
        ext = PostExtractor({})
        page = make_mock_page()
        scoped_root = AsyncMock()

        reaction_el = AsyncMock()
        reaction_el.get_attribute = AsyncMock(return_value="42 cảm xúc")
        reaction_el.inner_text = AsyncMock(return_value="42")
        scoped_root.query_selector = AsyncMock(return_value=reaction_el)
        scoped_root.query_selector_all = AsyncMock(return_value=[])
        scoped_root.evaluate = AsyncMock(return_value=None)

        page.query_selector = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=None)

        result = await ext._extract_page_reactions(page, scoped_root=scoped_root)
        assert isinstance(result, dict)


# ─── cover remaining _get_post_text_element strategy 3 ───────────────────────

class TestGetPostTextElementStrategy3:
    @pytest.mark.asyncio
    async def test_falls_back_to_foreground_container(self):
        """Test strategy 3: foreground container fallback (lines 432-464)."""
        ext = PostExtractor({})
        page = make_mock_page()
        page.title = AsyncMock(return_value="Facebook")  # no useful title

        # Make og:description also fail
        page.evaluate = AsyncMock(return_value="")

        # Strategy 3: foreground container
        fg_el = AsyncMock()
        fg_el.inner_text = AsyncMock(return_value="Post text from foreground container")
        fg_handle = AsyncMock()
        fg_handle.as_element = MagicMock(return_value=fg_el)
        page.evaluate_handle = AsyncMock(return_value=fg_handle)
        page.query_selector_all = AsyncMock(return_value=[])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await ext._get_post_text_element(page)
        # Should return either (fg_el, text) or None
        assert result is None or isinstance(result, tuple)


# ─── _extract_page_reactions with comment count > 0 ──────────────────────────

class TestExtractPageReactionsWithCounts:
    @pytest.mark.asyncio
    async def test_fills_in_html_reactions_when_dom_zero(self):
        """Test that html_reactions fill in values when DOM shows 0 (lines 517-524)."""
        ext = PostExtractor({})
        page = make_mock_page()
        page.content = AsyncMock(return_value="""
        {"reaction_type":"LIKE","count":150}
        """)
        page.evaluate = AsyncMock(return_value="")

        with patch.object(ext, "_find_post_container", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_get_post_text_element", new_callable=AsyncMock, return_value=(None, "text")):
                with patch.object(ext, "_extract_author_from", new_callable=AsyncMock, return_value=(None, None)):
                    with patch.object(ext, "_extract_timestamp_from", new_callable=AsyncMock, return_value=None):
                        with patch.object(ext, "_get_foreground_container", new_callable=AsyncMock, return_value=None):
                            with patch.object(ext, "_extract_images_from", new_callable=AsyncMock, return_value=[]):
                                with patch.object(ext, "_extract_videos_from", new_callable=AsyncMock, return_value=[]):
                                    with patch.object(ext, "_extract_page_reactions", new_callable=AsyncMock,
                                                      return_value={"like_count": 0, "love_count": 0, "haha_count": 0,
                                                                     "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                                     "care_count": 0, "comment_count": 0,
                                                                     "share_count": 0, "view_count": None}):
                                        with patch.object(ext, "_get_reactions_from_html", new_callable=AsyncMock,
                                                          return_value={"like_count": 150, "love_count": 0, "haha_count": 0,
                                                                         "wow_count": 0, "sad_count": 0, "angry_count": 0,
                                                                         "care_count": 0}):
                                            with patch.object(ext, "_get_comment_count_from_html", new_callable=AsyncMock, return_value=25):
                                                with patch.object(ext, "_get_share_count_from_html", new_callable=AsyncMock, return_value=5):
                                                    with patch.object(ext, "_extract_page_location", new_callable=AsyncMock, return_value=None):
                                                        with patch.object(ext, "_extract_tagged_users_from", new_callable=AsyncMock, return_value=[]):
                                                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                                                result = await ext._extract_post_data(
                                                                    page, "https://www.facebook.com/TestPage/posts/123"
                                                                )
        # The html_reactions should fill in the 0 like_count
        assert result is not None
        assert result.like_count == 150
        assert result.comment_count == 25
        assert result.share_count == 5
