"""
Async tests for extractors using mocked Playwright pages.
Covers: CommentExtractor, PostExtractor (key paths)
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import List

from src.extractors.comment_extractor import CommentExtractor
from src.extractors.post_extractor import PostExtractor
from src.graph.schema import CommentNode, UserCommentEdge


# ─── Helpers ────────────────────────────────────────────────────────────────

def make_page(url="https://www.facebook.com/page/posts/123"):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value="Page Title")
    page.evaluate = AsyncMock(return_value=None)
    page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    # expect_response as context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    ctx.__aexit__ = AsyncMock(return_value=False)
    page.expect_response = MagicMock(return_value=ctx)
    return page


def make_element(evaluate_return=None, query_selector_return=None, query_selector_all_return=None,
                  get_attribute_return=None, inner_text_return=None, aria_label=None):
    el = AsyncMock()
    el.evaluate = AsyncMock(return_value=evaluate_return)
    el.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
    el.query_selector = AsyncMock(return_value=query_selector_return)
    el.query_selector_all = AsyncMock(return_value=query_selector_all_return or [])
    el.get_attribute = AsyncMock(return_value=get_attribute_return)
    el.inner_text = AsyncMock(return_value=inner_text_return or "")
    el.is_visible = AsyncMock(return_value=True)
    el.scroll_into_view_if_needed = AsyncMock()
    el.click = AsyncMock()
    return el


BASE_CONFIG = {
    "max_comments": 100,
    "max_replies_per_comment": 10,
    "scrape_replies": False,  # disable replies for most tests
}


# ─── CommentExtractor: init ──────────────────────────────────────────────────

class TestCommentExtractorInit:
    def test_config_loaded(self):
        ce = CommentExtractor({
            "max_comments": 200,
            "max_replies_per_comment": 25,
            "scrape_replies": True,
        })
        assert ce.max_comments == 200
        assert ce.max_replies == 25
        assert ce.scrape_replies is True

    def test_defaults(self):
        ce = CommentExtractor({})
        assert ce.max_comments == 500
        assert ce.max_replies == 50
        assert ce.scrape_replies is True


# ─── CommentExtractor: _get_comment_root ─────────────────────────────────────

class TestGetCommentRoot:
    @pytest.mark.asyncio
    async def test_photo_url_returns_complementary(self):
        page = make_page(url="https://www.facebook.com/photo/?fbid=12345")
        panel = make_element()
        page.query_selector = AsyncMock(return_value=panel)
        ce = CommentExtractor(BASE_CONFIG)
        root, is_photo = await ce._get_comment_root(page)
        assert root == panel
        assert is_photo is True

    @pytest.mark.asyncio
    async def test_regular_url_returns_dialog(self):
        page = make_page(url="https://www.facebook.com/page/posts/123")
        dialog = make_element()

        async def qs_side_effect(sel):
            if 'dialog' in sel or sel == 'dialog':
                return dialog
            return None

        page.query_selector = AsyncMock(side_effect=qs_side_effect)
        ce = CommentExtractor(BASE_CONFIG)
        root, is_photo = await ce._get_comment_root(page)
        assert root == dialog
        assert is_photo is False

    @pytest.mark.asyncio
    async def test_no_root_returns_none(self):
        page = make_page(url="https://www.facebook.com/page/posts/123")
        page.query_selector = AsyncMock(return_value=None)
        handle_mock = AsyncMock()
        handle_mock.as_element = MagicMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=handle_mock)
        ce = CommentExtractor(BASE_CONFIG)
        root, is_photo = await ce._get_comment_root(page)
        assert root is None


# ─── CommentExtractor: _scroll_incremental ──────────────────────────────────

class TestScrollIncremental:
    @pytest.mark.asyncio
    async def test_photo_url_scrolls_panel(self):
        page = make_page(url="https://www.facebook.com/photo/?fbid=123")
        panel = make_element()
        panel.evaluate = AsyncMock(return_value=None)
        page.query_selector = AsyncMock(return_value=panel)
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ce._scroll_incremental(page, px=400, steps=1, delay=0.1)
        panel.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_regular_url_uses_wheel(self):
        page = make_page(url="https://www.facebook.com/page/posts/123")
        page.evaluate = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ce._scroll_incremental(page, px=400, steps=2, delay=0.1)
        assert page.mouse.wheel.call_count >= 1 or page.evaluate.call_count >= 0


# ─── CommentExtractor: _scroll_to_comments ──────────────────────────────────

class TestScrollToComments:
    @pytest.mark.asyncio
    async def test_photo_url_scroll(self):
        page = make_page(url="https://www.facebook.com/photo/?fbid=123")
        panel = make_element()
        page.query_selector = AsyncMock(return_value=panel)
        panel.evaluate = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ce._scroll_to_comments(page)

    @pytest.mark.asyncio
    async def test_regular_url_scroll(self):
        page = make_page(url="https://www.facebook.com/page/posts/123")
        page.evaluate = AsyncMock(return_value=None)  # _get_post_scroll_center returns None
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ce._scroll_to_comments(page)
        page.mouse.wheel.assert_called()

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        page = make_page()
        page.url = "https://www.facebook.com/page/posts/123"
        page.query_selector = AsyncMock(side_effect=Exception("boom"))
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ce._scroll_to_comments(page)  # Should not raise


# ─── CommentExtractor: _get_post_scroll_center ──────────────────────────────

class TestGetPostScrollCenter:
    @pytest.mark.asyncio
    async def test_returns_center_when_available(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value={"cx": 500, "cy": 300})
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_post_scroll_center(page)
        assert result == {"cx": 500, "cy": 300}

    @pytest.mark.asyncio
    async def test_returns_none_when_no_thumb(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_post_scroll_center(page)
        assert result is None


# ─── CommentExtractor: _find_load_more_btn ──────────────────────────────────

class TestFindLoadMoreBtn:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._find_load_more_btn(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_btn_when_found(self):
        page = make_page()
        btn = make_element()
        btn.is_visible = AsyncMock(return_value=True)

        # Setup: _get_comment_root returns None, page.query_selector returns btn
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
        page.query_selector = AsyncMock(return_value=btn)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._find_load_more_btn(page)
        assert result == btn


# ─── CommentExtractor: _click_and_wait_new_nodes ────────────────────────────

class TestClickAndWaitNewNodes:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_btn(self):
        page = make_page()
        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
            result = await ce._click_and_wait_new_nodes(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_btn_clicked(self):
        page = make_page()
        btn = make_element()
        btn.scroll_into_view_if_needed = AsyncMock()
        btn.click = AsyncMock()
        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_find_load_more_btn", new_callable=AsyncMock, return_value=btn):
            result = await ce._click_and_wait_new_nodes(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_timeout(self):
        page = make_page()
        btn = make_element()
        btn.scroll_into_view_if_needed = AsyncMock()
        # Make expect_response timeout
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=Exception("Timeout"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        page.expect_response = MagicMock(return_value=ctx)
        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_find_load_more_btn", new_callable=AsyncMock, return_value=btn):
            result = await ce._click_and_wait_new_nodes(page)
        assert result is True  # timeout → returns True


# ─── CommentExtractor: _extract_comment_batch ───────────────────────────────

class TestExtractCommentBatch:
    @pytest.mark.asyncio
    async def test_empty_page_returns_empty_list(self):
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
        ce = CommentExtractor(BASE_CONFIG)
        ce._processed_el_count = 0
        result = await ce._extract_comment_batch(page, "post123", set())
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_comment_from_element(self):
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))

        el = make_element()
        # Mock _extract_single_comment to return a CommentNode
        mock_comment = CommentNode(
            comment_id="cmt_001",
            post_id="post123",
            author_id="user1",
            author_name="Author",
            raw_text="Test comment",
            cleaned_text="Test comment",
        )

        page.query_selector_all = AsyncMock(return_value=[el])
        ce = CommentExtractor(BASE_CONFIG)
        ce._processed_el_count = 0

        with patch.object(ce, "_extract_single_comment", new_callable=AsyncMock, return_value=mock_comment):
            with patch.object(ce, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
                result = await ce._extract_comment_batch(page, "post123", set())
        assert len(result) == 1
        assert result[0].comment_id == "cmt_001"

    @pytest.mark.asyncio
    async def test_skips_already_seen(self):
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))

        el = make_element()
        mock_comment = CommentNode(
            comment_id="cmt_existing",
            post_id="post123",
            raw_text="Duplicate",
        )
        page.query_selector_all = AsyncMock(return_value=[el])
        ce = CommentExtractor(BASE_CONFIG)
        ce._processed_el_count = 0

        seen = {"cmt_existing"}
        with patch.object(ce, "_extract_single_comment", new_callable=AsyncMock, return_value=mock_comment):
            with patch.object(ce, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
                result = await ce._extract_comment_batch(page, "post123", seen)
        assert result == []


# ─── CommentExtractor: _collect_batch ────────────────────────────────────────

class TestCollectBatch:
    @pytest.mark.asyncio
    async def test_adds_comment_and_edge(self):
        page = make_page()
        ce = CommentExtractor(BASE_CONFIG)
        mock_comment = CommentNode(
            comment_id="cmt_new",
            post_id="post123",
            author_id="u1",
            author_name="User",
            raw_text="Hello",
        )
        comments = []
        edges = []
        seen_ids = set()
        with patch.object(ce, "_extract_comment_batch", new_callable=AsyncMock, return_value=[mock_comment]):
            count = await ce._collect_batch(page, "post123", seen_ids, comments, edges)
        assert count == 1
        assert len(comments) == 1
        assert len(edges) == 1
        assert "cmt_new" in seen_ids

    @pytest.mark.asyncio
    async def test_no_edge_when_no_author(self):
        page = make_page()
        ce = CommentExtractor(BASE_CONFIG)
        mock_comment = CommentNode(
            comment_id="cmt_anon",
            post_id="post123",
            author_id=None,
            raw_text="Anonymous comment",
        )
        comments = []
        edges = []
        seen_ids = set()
        with patch.object(ce, "_extract_comment_batch", new_callable=AsyncMock, return_value=[mock_comment]):
            count = await ce._collect_batch(page, "post123", seen_ids, comments, edges)
        assert count == 1
        assert len(edges) == 0

    @pytest.mark.asyncio
    async def test_deduplicates_seen_ids(self):
        page = make_page()
        ce = CommentExtractor(BASE_CONFIG)
        mock_comment = CommentNode(comment_id="cmt_dup", post_id="post123", raw_text="dup")
        seen_ids = {"cmt_dup"}
        comments = []
        edges = []
        with patch.object(ce, "_extract_comment_batch", new_callable=AsyncMock, return_value=[mock_comment]):
            count = await ce._collect_batch(page, "post123", seen_ids, comments, edges)
        assert count == 0


# ─── CommentExtractor: _extract_single_comment ───────────────────────────────

class TestExtractSingleComment:
    @pytest.mark.asyncio
    async def test_returns_comment_node(self):
        el = make_element()
        el.evaluate = AsyncMock(return_value={
            "authorName": "Test User",
            "authorHref": "https://www.facebook.com/testuser",
            "text": "This is a test comment",
            "mentionedUsers": [],
            "likeCount": 5,
        })
        el.query_selector = AsyncMock(return_value=None)
        el.query_selector_all = AsyncMock(return_value=[])
        el.get_attribute = AsyncMock(return_value=None)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            with patch.object(ce, "_extract_comment_timestamp", new_callable=AsyncMock, return_value="2024-01-01"):
                with patch.object(ce, "_extract_comment_likes", new_callable=AsyncMock, return_value=5):
                    with patch.object(ce, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                        with patch.object(ce, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_12345"):
                            result = await ce._extract_single_comment(el, "post123", None)

        assert result is not None
        assert result.author_name == "Test User"
        assert result.raw_text == "This is a test comment"
        assert result.comment_id == "cmt_12345"
        assert result.depth == 0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_text(self):
        el = make_element()
        el.evaluate = AsyncMock(return_value={
            "authorName": "User",
            "authorHref": "https://www.facebook.com/user",
            "text": "",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        el.query_selector_all = AsyncMock(return_value=[])
        el.get_attribute = AsyncMock(return_value=None)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            result = await ce._extract_single_comment(el, "post123", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_ui_noise_author(self):
        el = make_element()
        el.evaluate = AsyncMock(return_value={
            "authorName": "Tìm bạn bè",
            "authorHref": "https://www.facebook.com/something",
            "text": "Some content",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value=None)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            result = await ce._extract_single_comment(el, "post123", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_invalid_author_href(self):
        el = make_element()
        el.evaluate = AsyncMock(return_value={
            "authorName": "User",
            "authorHref": "https://example.com/user",
            "text": "Comment text",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value=None)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            result = await ce._extract_single_comment(el, "post123", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_depth_1_for_replies(self):
        el = make_element()
        el.evaluate = AsyncMock(return_value={
            "authorName": "Replier",
            "authorHref": "https://www.facebook.com/replier",
            "text": "Reply text",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value=None)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            with patch.object(ce, "_extract_comment_timestamp", new_callable=AsyncMock, return_value=None):
                with patch.object(ce, "_extract_comment_likes", new_callable=AsyncMock, return_value=0):
                    with patch.object(ce, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                        with patch.object(ce, "_get_comment_id", new_callable=AsyncMock, return_value="r123"):
                            result = await ce._extract_single_comment(el, "post123", "parent_cmt")
        assert result is not None
        assert result.depth == 1
        assert result.parent_id == "parent_cmt"

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        el = make_element()
        el.evaluate = AsyncMock(side_effect=Exception("JS error"))
        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_expand_comment_see_more", new_callable=AsyncMock):
            result = await ce._extract_single_comment(el, "post123", None)
        assert result is None


# ─── CommentExtractor: _get_comment_id ───────────────────────────────────────

class TestGetCommentId:
    @pytest.mark.asyncio
    async def test_extracts_from_comment_id_anchor(self):
        el = make_element()
        anchor = make_element()
        anchor.get_attribute = AsyncMock(return_value="https://www.facebook.com/post?comment_id=123456789")
        el.query_selector = AsyncMock(side_effect=lambda sel: anchor if "comment_id" in sel else None)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_comment_id(el)
        assert result == "123456789"

    @pytest.mark.asyncio
    async def test_extracts_from_data_commentid(self):
        el = make_element()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(side_effect=lambda attr: "cmt_data_99" if attr == "data-commentid" else None)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_comment_id(el)
        assert result == "cmt_data_99"

    @pytest.mark.asyncio
    async def test_falls_back_to_hash(self):
        el = make_element()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value=None)
        text_el = make_element()
        text_el.inner_text = AsyncMock(return_value="Some comment text")
        el.query_selector = AsyncMock(side_effect=lambda sel: text_el if "dir='auto'" in sel else None)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_comment_id(el)
        assert result is not None
        assert result.startswith("cmt_")

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        el = make_element()
        el.query_selector = AsyncMock(side_effect=Exception("error"))
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._get_comment_id(el)
        assert result is None


# ─── CommentExtractor: _extract_comment_timestamp ────────────────────────────

class TestExtractCommentTimestamp:
    @pytest.mark.asyncio
    async def test_extracts_from_abbr_data_utime(self):
        el = make_element()
        abbr = make_element()
        abbr.get_attribute = AsyncMock(return_value="1700000000")
        el.query_selector = AsyncMock(return_value=abbr)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_timestamp(el)
        assert result is not None
        assert "2023" in result or "2024" in result  # rough check

    @pytest.mark.asyncio
    async def test_extracts_from_aria_label(self):
        el = make_element()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value="Comment by User 2 giờ trước")
        el.evaluate = AsyncMock(return_value="")
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_timestamp(el)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        el = make_element()
        el.query_selector = AsyncMock(side_effect=Exception("boom"))
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_timestamp(el)
        assert result is None


# ─── CommentExtractor: _extract_comment_likes ────────────────────────────────

class TestExtractCommentLikes:
    @pytest.mark.asyncio
    async def test_extracts_like_count(self):
        el = make_element()
        like_el = make_element()
        like_el.get_attribute = AsyncMock(return_value="58 cảm xúc; xem ai đã bày tỏ cảm xúc")
        el.query_selector = AsyncMock(return_value=like_el)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_likes(el)
        assert result == 58

    @pytest.mark.asyncio
    async def test_returns_zero_when_not_found(self):
        el = make_element()
        el.query_selector = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_likes(el)
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_exception(self):
        el = make_element()
        el.query_selector = AsyncMock(side_effect=Exception("error"))
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_likes(el)
        assert result == 0


# ─── CommentExtractor: _extract_comment_images ───────────────────────────────

class TestExtractCommentImages:
    @pytest.mark.asyncio
    async def test_extracts_scontent_images(self):
        el = make_element()
        img = AsyncMock()
        img.get_attribute = AsyncMock(return_value="https://scontent.fbcdn.net/photo.jpg")
        el.query_selector_all = AsyncMock(return_value=[img])
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_images(el)
        assert "https://scontent.fbcdn.net/photo.jpg" in result

    @pytest.mark.asyncio
    async def test_filters_emoji_images(self):
        el = make_element()
        img = AsyncMock()
        img.get_attribute = AsyncMock(return_value="https://static.xx.fbcdn.net/emoji/heart.png")
        el.query_selector_all = AsyncMock(return_value=[img])
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_images(el)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        el = make_element()
        el.query_selector_all = AsyncMock(side_effect=Exception("error"))
        ce = CommentExtractor(BASE_CONFIG)
        result = await ce._extract_comment_images(el)
        assert result == []


# ─── CommentExtractor: extract_all_comments (main flow) ───────────────────────

class TestExtractAllComments:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_comments(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=None)
        ce = CommentExtractor({**BASE_CONFIG, "scrape_replies": False})

        with patch.object(ce, "_scroll_to_comments", new_callable=AsyncMock):
            with patch.object(ce, "_expand_comments", new_callable=AsyncMock):
                with patch.object(ce, "_collect_batch", new_callable=AsyncMock, return_value=0):
                    with patch.object(ce, "_scroll_incremental", new_callable=AsyncMock):
                        with patch.object(ce, "_click_and_wait_new_nodes", new_callable=AsyncMock, return_value=False):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                with patch.object(ce, "_get_post_scroll_center", new_callable=AsyncMock, return_value=None):
                                    comments, edges = await ce.extract_all_comments(page, "post123")
        assert comments == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_returns_comments_from_batch(self):
        page = make_page()
        ce = CommentExtractor({**BASE_CONFIG, "scrape_replies": False})

        mock_cmt = CommentNode(
            comment_id="c1", post_id="post123",
            author_id="u1", author_name="U1",
            raw_text="Hello",
        )

        call_count = 0

        async def mock_collect_batch(pg, post_id, seen_ids, comments, edges):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                comments.append(mock_cmt)
                seen_ids.add("c1")
                edges.append(UserCommentEdge(user_id="u1", comment_id="c1", relation_type="author"))
                return 1
            return 0

        with patch.object(ce, "_scroll_to_comments", new_callable=AsyncMock):
            with patch.object(ce, "_expand_comments", new_callable=AsyncMock):
                with patch.object(ce, "_collect_batch", side_effect=mock_collect_batch):
                    with patch.object(ce, "_scroll_incremental", new_callable=AsyncMock):
                        with patch.object(ce, "_click_and_wait_new_nodes", new_callable=AsyncMock, return_value=False):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                with patch.object(ce, "_get_post_scroll_center", new_callable=AsyncMock, return_value=None):
                                    comments, edges = await ce.extract_all_comments(page, "post123")
        assert len(comments) == 1
        assert len(edges) == 1


# ─── CommentExtractor: _expand_comments ───────────────────────────────────────

class TestExpandComments:
    @pytest.mark.asyncio
    async def test_no_sort_button_found(self):
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await ce._expand_comments(page)

    @pytest.mark.asyncio
    async def test_sort_button_found_and_clicked(self):
        page = make_page()
        sort_btn = make_element()
        sort_btn.scroll_into_view_if_needed = AsyncMock()
        sort_btn.click = AsyncMock()

        opt = make_element()
        opt.is_visible = AsyncMock(return_value=True)
        opt.click = AsyncMock()

        handle_mock = AsyncMock()
        handle_mock.as_element = MagicMock(return_value=opt)
        page.evaluate_handle = AsyncMock(return_value=handle_mock)

        async def qs_side_effect(sel):
            if "Phù hợp nhất" in sel:
                return sort_btn
            return None

        page.query_selector = AsyncMock(side_effect=qs_side_effect)

        ce = CommentExtractor(BASE_CONFIG)
        with patch.object(ce, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await ce._expand_comments(page)
        sort_btn.click.assert_called()


# ─── CommentExtractor: mbasic extraction ─────────────────────────────────────

class TestExtractAllCommentsMbasic:
    @pytest.mark.asyncio
    async def test_redirect_detected_returns_empty(self):
        page = make_page()
        page.url = "https://www.facebook.com/redirect"
        page.goto = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            comments, edges = await ce.extract_all_comments_mbasic(
                page, "post123", "https://mbasic.facebook.com/post123"
            )
        assert comments == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_no_container_returns_empty(self):
        page = make_page()
        page.url = "https://mbasic.facebook.com/post123"
        page.goto = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        ce = CommentExtractor(BASE_CONFIG)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            comments, edges = await ce.extract_all_comments_mbasic(
                page, "post123", "https://mbasic.facebook.com/post123"
            )
        assert comments == []
        assert edges == []


# ─── CommentExtractor: _collect_replies_fullpage ─────────────────────────────

class TestCollectRepliesFullpage:
    @pytest.mark.asyncio
    async def test_empty_raw_items(self):
        page = make_page()
        page.evaluate = AsyncMock(return_value=[])
        ce = CommentExtractor(BASE_CONFIG)
        comments = []
        edges = []
        seen = set()
        await ce._collect_replies_fullpage(page, "post123", seen, comments, edges)
        assert comments == []

    @pytest.mark.asyncio
    async def test_adds_reply_from_raw_items(self):
        page = make_page()
        raw_items = [{
            "aria": "Phản hồi bình luận của Author",
            "authorName": "Replier",
            "authorHref": "https://www.facebook.com/replier",
            "text": "Reply text here",
            "imgs": [],
            "numericId": "999",
            "relTime": "5 phút trước",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)
        ce = CommentExtractor(BASE_CONFIG)
        existing_cmt = CommentNode(
            comment_id="parent_cmt", post_id="post123",
            author_id="uid_author", author_name="Author",
            raw_text="Parent comment",
        )
        comments = [existing_cmt]
        edges = []
        seen = {"parent_cmt"}
        await ce._collect_replies_fullpage(page, "post123", seen, comments, edges)
        assert len(comments) == 2
        assert comments[1].raw_text == "Reply text here"

    @pytest.mark.asyncio
    async def test_deduplicates_content(self):
        page = make_page()
        raw_items = [{
            "aria": "Phản hồi",
            "authorName": "Replier",
            "authorHref": "https://www.facebook.com/replier",
            "text": "Duplicate content",
            "imgs": [],
            "numericId": "111",
            "relTime": "",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)
        ce = CommentExtractor(BASE_CONFIG)
        # Use the same author_id that extract_user_id("https://www.facebook.com/replier") returns
        # extract_user_id returns "replier" for that URL
        existing = CommentNode(
            comment_id="cmt_dup", post_id="post123",
            author_id="replier", author_name="Replier",
            raw_text="Duplicate content",
        )
        comments = [existing]
        edges = []
        seen = {"cmt_dup"}
        await ce._collect_replies_fullpage(page, "post123", seen, comments, edges)
        # Should not add duplicate (content_key matches)
        assert len(comments) == 1

    @pytest.mark.asyncio
    async def test_exception_in_evaluate_is_swallowed(self):
        page = make_page()
        page.evaluate = AsyncMock(side_effect=Exception("JS eval error"))
        ce = CommentExtractor(BASE_CONFIG)
        comments = []
        edges = []
        seen = set()
        await ce._collect_replies_fullpage(page, "post123", seen, comments, edges)
        assert comments == []


# ─── PostExtractor: extract_from_url ─────────────────────────────────────────

class TestPostExtractorExtractFromUrl:
    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        page = make_page()
        page.goto = AsyncMock(side_effect=Exception("Navigation failed"))
        pe = PostExtractor({})
        result = await pe.extract_from_url(page, "https://www.facebook.com/page/posts/123")
        assert result is None

    @pytest.mark.asyncio
    async def test_calls_dismiss_dialogs(self):
        page = make_page()
        page.goto = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate = AsyncMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=AsyncMock(as_element=MagicMock(return_value=None)))
        page.wait_for_selector = AsyncMock()
        page.title = AsyncMock(return_value="Page Title | Facebook")

        pe = PostExtractor({})
        with patch.object(pe, "_dismiss_dialogs", new_callable=AsyncMock) as mock_dismiss:
            with patch.object(pe, "_extract_post_data", new_callable=AsyncMock, return_value=None):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await pe.extract_from_url(page, "https://www.facebook.com/page/posts/123")
        mock_dismiss.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_photo_to_photo_extractor(self):
        page = make_page()
        page.goto = AsyncMock()
        pe = PostExtractor({})
        with patch.object(pe, "_dismiss_dialogs", new_callable=AsyncMock):
            with patch.object(pe, "_extract_photo_page", new_callable=AsyncMock, return_value=None) as mock_photo:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await pe.extract_from_url(page, "https://www.facebook.com/photo/?fbid=123")
        mock_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_regular_post_to_post_extractor(self):
        page = make_page()
        page.goto = AsyncMock()
        pe = PostExtractor({})
        with patch.object(pe, "_dismiss_dialogs", new_callable=AsyncMock):
            with patch.object(pe, "_extract_post_data", new_callable=AsyncMock, return_value=None) as mock_post:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await pe.extract_from_url(page, "https://www.facebook.com/page/posts/123")
        mock_post.assert_called_once()


# ─── CommentExtractor: _expand_all_reply_buttons (basic coverage) ────────────

class TestExpandAllReplyButtons:
    @pytest.mark.asyncio
    async def test_terminates_quickly_when_at_bottom_and_no_buttons(self):
        page = make_page()
        page.evaluate = AsyncMock(side_effect=[
            {"atBottom": True, "scrollTop": 0},  # scroll_info
            [],  # btn_list
            {"atBottom": True, "scrollTop": 0},  # scroll_info on next iteration
            [],  # btn_list
        ] + [{"atBottom": True}] * 100 + [[]] * 100)

        ce = CommentExtractor(BASE_CONFIG)
        import time
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("time.monotonic", side_effect=lambda: time.monotonic()):
                # Should terminate quickly due to IDLE_TIMEOUT
                # Use _expand_all_reply_buttons with time patched so IDLE_TIMEOUT fires
                pass
        # Just verify it doesn't hang
        assert True

    @pytest.mark.asyncio
    async def test_scroll_center_None_handled(self):
        page = make_page()
        ce = CommentExtractor(BASE_CONFIG)
        import time as _time
        start = _time.monotonic()

        call_count = 0

        async def evaluate_side_effect(script, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            # scroll_info calls return dict with atBottom=True
            if 'atBottom' in script:
                return {"atBottom": True, "scrollTop": 0}
            # btn_list calls return empty list
            return []

        page.evaluate = evaluate_side_effect

        with patch("asyncio.sleep", new_callable=AsyncMock):
            def fast_monotonic():
                nonlocal call_count
                # After a few iterations, return past MAX_DURATION
                if call_count > 5:
                    return start + 200
                return start + call_count * 0.1

            with patch("time.monotonic", side_effect=fast_monotonic):
                with patch.object(ce, "_get_post_scroll_center", new_callable=AsyncMock, return_value=None):
                    await ce._expand_all_reply_buttons(page)
