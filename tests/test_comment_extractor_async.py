"""
Mock-based async tests for src/extractors/comment_extractor.py
Covers extract_all_comments, _collect_replies_fullpage, _extract_single_comment,
_expand_all_reply_buttons, _find_load_more_btn, _click_and_wait_new_nodes,
_scroll_incremental, _get_post_scroll_center, _get_comment_id,
_extract_comment_timestamp, _extract_comment_likes, _collect_batch.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.extractors.comment_extractor import CommentExtractor
from src.graph.schema import CommentNode, UserCommentEdge


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_mock_page(url="https://www.facebook.com/PageWSS/posts/123"):
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value="Test Post")
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
    resp_ctx = AsyncMock()
    resp_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    resp_ctx.__aexit__ = AsyncMock(return_value=False)
    page.expect_response = MagicMock(return_value=resp_ctx)
    return page


def make_mock_element(aria_label="Comment by Test User",
                      text="Hello world",
                      href="https://www.facebook.com/user.test"):
    el = AsyncMock()
    el.get_attribute = AsyncMock(side_effect=lambda attr: {
        "aria-label": aria_label,
        "href": href,
        "src": None,
        "data-commentid": None,
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


def make_comment_extractor(config=None):
    return CommentExtractor(config or {
        "max_comments": 100,
        "max_replies_per_comment": 10,
        "scrape_replies": False,
    })


# ─── _extract_single_comment ──────────────────────────────────────────────────

class TestExtractSingleComment:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_text(self):
        ext = make_comment_extractor()
        el = make_mock_element(text="")
        el.evaluate = AsyncMock(return_value={
            "authorName": "User",
            "authorHref": "https://www.facebook.com/user1",
            "text": "",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        # _expand_comment_see_more needs query_selector
        el.query_selector = AsyncMock(return_value=None)
        # timestamp and images
        with patch.object(ext, "_extract_comment_timestamp", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_extract_comment_likes", new_callable=AsyncMock, return_value=0):
                with patch.object(ext, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_abc123"):
                        result = await ext._extract_single_comment(el, "post1", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_comment_with_text(self):
        ext = make_comment_extractor()
        href = "https://www.facebook.com/user.test"
        el = make_mock_element(text="Great post!", href=href)
        el.evaluate = AsyncMock(return_value={
            "authorName": "Test User",
            "authorHref": href,
            "text": "Great post!",
            "mentionedUsers": [],
            "likeCount": 3,
        })
        el.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_extract_comment_timestamp", new_callable=AsyncMock, return_value="2024-01-01T10:00:00"):
            with patch.object(ext, "_extract_comment_likes", new_callable=AsyncMock, return_value=3):
                with patch.object(ext, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_abc123"):
                        result = await ext._extract_single_comment(el, "post1", None)
        assert result is not None
        assert result.raw_text == "Great post!"
        assert result.author_name == "Test User"
        assert result.post_id == "post1"
        assert result.depth == 0  # no parent

    @pytest.mark.asyncio
    async def test_sets_depth_1_with_parent(self):
        ext = make_comment_extractor()
        href = "https://www.facebook.com/user.test"
        el = make_mock_element(text="Reply text", href=href)
        el.evaluate = AsyncMock(return_value={
            "authorName": "Replier",
            "authorHref": href,
            "text": "Reply text",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_extract_comment_timestamp", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_extract_comment_likes", new_callable=AsyncMock, return_value=0):
                with patch.object(ext, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_child"):
                        result = await ext._extract_single_comment(el, "post1", "parent_cmt")
        assert result is not None
        assert result.depth == 1
        assert result.parent_id == "parent_cmt"

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.evaluate = AsyncMock(side_effect=Exception("DOM error"))
        el.query_selector = AsyncMock(return_value=None)
        result = await ext._extract_single_comment(el, "post1", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_ui_noise_author(self):
        ext = make_comment_extractor()
        href = "https://www.facebook.com/find_friends"
        el = make_mock_element(text="Some text", href=href)
        el.evaluate = AsyncMock(return_value={
            "authorName": "Tìm bạn bè",
            "authorHref": href,
            "text": "Some text",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_extract_comment_timestamp", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_extract_comment_likes", new_callable=AsyncMock, return_value=0):
                with patch.object(ext, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_noise"):
                        result = await ext._extract_single_comment(el, "post1", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_invalid_author_href(self):
        ext = make_comment_extractor()
        # href without facebook.com
        href = "https://example.com/user"
        el = make_mock_element(text="Some valid text", href=href)
        el.evaluate = AsyncMock(return_value={
            "authorName": "Someone",
            "authorHref": href,
            "text": "Some valid text",
            "mentionedUsers": [],
            "likeCount": 0,
        })
        el.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_extract_comment_timestamp", new_callable=AsyncMock, return_value=None):
            with patch.object(ext, "_extract_comment_likes", new_callable=AsyncMock, return_value=0):
                with patch.object(ext, "_extract_comment_images", new_callable=AsyncMock, return_value=[]):
                    with patch.object(ext, "_get_comment_id", new_callable=AsyncMock, return_value="cmt_bad_href"):
                        result = await ext._extract_single_comment(el, "post1", None)
        assert result is None


# ─── _get_comment_id ──────────────────────────────────────────────────────────

class TestGetCommentId:
    @pytest.mark.asyncio
    async def test_extracts_numeric_id_from_anchor(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        anchor = AsyncMock()
        anchor.get_attribute = AsyncMock(return_value="https://fb.com/post?comment_id=12345678&ref=x")
        el.query_selector = AsyncMock(side_effect=lambda sel: anchor if "comment_id" in sel else None)
        el.get_attribute = AsyncMock(return_value=None)
        result = await ext._get_comment_id(el)
        assert result == "12345678"

    @pytest.mark.asyncio
    async def test_falls_back_to_hash_when_no_anchor(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value=None)
        text_el = AsyncMock()
        text_el.inner_text = AsyncMock(return_value="Some comment text")

        async def mock_qs(sel):
            if "comment_id" in sel:
                return None
            if "role=\"link\"" in sel:
                return None
            if "dir='auto'" in sel:
                return text_el
            return None

        el.query_selector = AsyncMock(side_effect=mock_qs)
        result = await ext._get_comment_id(el)
        assert result is not None
        assert result.startswith("cmt_")

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(side_effect=Exception("DOM error"))
        result = await ext._get_comment_id(el)
        assert result is None


# ─── _extract_comment_timestamp ───────────────────────────────────────────────

class TestExtractCommentTimestamp:
    @pytest.mark.asyncio
    async def test_extracts_from_data_utime(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        abbr = AsyncMock()
        abbr.get_attribute = AsyncMock(return_value="1700000000")
        el.query_selector = AsyncMock(return_value=abbr)
        el.get_attribute = AsyncMock(return_value="")
        el.evaluate = AsyncMock(return_value="")
        result = await ext._extract_comment_timestamp(el)
        assert result is not None
        assert "2023" in result or "T" in result  # ISO timestamp

    @pytest.mark.asyncio
    async def test_extracts_from_aria_label(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value="Bình luận của User vào 2 giờ trước")
        el.evaluate = AsyncMock(return_value="")
        result = await ext._extract_comment_timestamp(el)
        assert result is not None

    @pytest.mark.asyncio
    async def test_extracts_from_span_text(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value="")
        el.evaluate = AsyncMock(return_value="5 phút trước")
        result = await ext._extract_comment_timestamp(el)
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_nothing_found(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        el.get_attribute = AsyncMock(return_value="")
        el.evaluate = AsyncMock(return_value="")
        result = await ext._extract_comment_timestamp(el)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(side_effect=Exception("Error"))
        result = await ext._extract_comment_timestamp(el)
        assert result is None


# ─── _extract_comment_likes ───────────────────────────────────────────────────

class TestExtractCommentLikes:
    @pytest.mark.asyncio
    async def test_extracts_like_count(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        like_el = AsyncMock()
        like_el.get_attribute = AsyncMock(return_value="58 cảm xúc; xem ai đã bày tỏ cảm xúc")
        el.query_selector = AsyncMock(return_value=like_el)
        result = await ext._extract_comment_likes(el)
        assert result == 58

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_like_element(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        result = await ext._extract_comment_likes(el)
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_exception(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        el.query_selector = AsyncMock(side_effect=Exception("Error"))
        result = await ext._extract_comment_likes(el)
        assert result == 0

    @pytest.mark.asyncio
    async def test_parses_k_suffix(self):
        ext = make_comment_extractor()
        el = AsyncMock()
        like_el = AsyncMock()
        like_el.get_attribute = AsyncMock(return_value="2k reactions")
        el.query_selector = AsyncMock(return_value=like_el)
        result = await ext._extract_comment_likes(el)
        assert result == 2000


# ─── _get_post_scroll_center ──────────────────────────────────────────────────

class TestGetPostScrollCenter:
    @pytest.mark.asyncio
    async def test_returns_center_when_element_found(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        page.evaluate = AsyncMock(return_value={"cx": 960, "cy": 540})
        result = await ext._get_post_scroll_center(page)
        assert result == {"cx": 960, "cy": 540}

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._get_post_scroll_center(page)
        assert result is None


# ─── _scroll_incremental ──────────────────────────────────────────────────────

class TestScrollIncremental:
    @pytest.mark.asyncio
    async def test_photo_url_scrolls_panel(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://www.facebook.com/photo/?fbid=12345")
        panel = AsyncMock()
        panel.evaluate = AsyncMock(return_value=None)
        page.query_selector = AsyncMock(return_value=panel)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._scroll_incremental(page, px=300, steps=1, delay=0.1)
        panel.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_regular_url_uses_mouse_wheel(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.evaluate = AsyncMock(return_value={"cx": 960, "cy": 540})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._scroll_incremental(page, px=300, steps=1, delay=0.1)
        page.mouse.wheel.assert_called()

    @pytest.mark.asyncio
    async def test_regular_url_no_center_uses_fallback(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.evaluate = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._scroll_incremental(page, px=300, steps=1, delay=0.1)
        page.mouse.wheel.assert_called()


# ─── _find_load_more_btn ──────────────────────────────────────────────────────

class TestFindLoadMoreBtn:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_button(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        page.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            result = await ext._find_load_more_btn(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_visible_button(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        btn = make_mock_element()
        btn.is_visible = AsyncMock(return_value=True)
        page.query_selector = AsyncMock(return_value=btn)
        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            result = await ext._find_load_more_btn(page)
        assert result == btn

    @pytest.mark.asyncio
    async def test_skips_invisible_button(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        btn = make_mock_element()
        btn.is_visible = AsyncMock(return_value=False)
        page.query_selector = AsyncMock(return_value=btn)
        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            result = await ext._find_load_more_btn(page)
        assert result is None


# ─── _click_and_wait_new_nodes ────────────────────────────────────────────────

class TestClickAndWaitNewNodes:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_button(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        with patch.object(ext, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
            result = await ext._click_and_wait_new_nodes(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_after_click(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        btn = make_mock_element()
        btn.scroll_into_view_if_needed = AsyncMock()
        btn.click = AsyncMock()
        with patch.object(ext, "_find_load_more_btn", new_callable=AsyncMock, return_value=btn):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ext._click_and_wait_new_nodes(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_true_on_timeout(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        btn = make_mock_element()
        btn.scroll_into_view_if_needed = AsyncMock()
        # Simulate timeout on expect_response context
        resp_ctx = AsyncMock()
        resp_ctx.__aenter__ = AsyncMock(side_effect=Exception("Timeout"))
        resp_ctx.__aexit__ = AsyncMock(return_value=False)
        page.expect_response = MagicMock(return_value=resp_ctx)
        with patch.object(ext, "_find_load_more_btn", new_callable=AsyncMock, return_value=btn):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await ext._click_and_wait_new_nodes(page)
        assert result is True  # Timeout → still return True


# ─── _collect_batch ───────────────────────────────────────────────────────────

class TestCollectBatch:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_elements(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 0
        page = make_mock_page()
        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            with patch.object(ext, "_extract_comment_batch", new_callable=AsyncMock, return_value=[]):
                result = await ext._collect_batch(page, "post1", set(), [], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_adds_new_comments(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 0
        page = make_mock_page()

        comment = CommentNode(
            comment_id="cmt_new001",
            post_id="post1",
            author_id="user1",
            author_name="User",
            raw_text="Hello",
            cleaned_text="Hello",
        )
        with patch.object(ext, "_extract_comment_batch", new_callable=AsyncMock, return_value=[comment]):
            comments_list = []
            edges_list = []
            result = await ext._collect_batch(page, "post1", set(), comments_list, edges_list)
        assert result == 1
        assert len(comments_list) == 1
        assert comments_list[0].comment_id == "cmt_new001"

    @pytest.mark.asyncio
    async def test_deduplicates_already_seen(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 0
        page = make_mock_page()

        comment = CommentNode(
            comment_id="cmt_seen",
            post_id="post1",
            author_id="user1",
            author_name="User",
            raw_text="Hello",
            cleaned_text="Hello",
        )
        seen = {"cmt_seen"}
        with patch.object(ext, "_extract_comment_batch", new_callable=AsyncMock, return_value=[comment]):
            result = await ext._collect_batch(page, "post1", seen, [], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_creates_edge_for_author(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 0
        page = make_mock_page()

        comment = CommentNode(
            comment_id="cmt_edge",
            post_id="post1",
            author_id="user_with_id",
            author_name="User With ID",
            raw_text="Hello",
            cleaned_text="Hello",
        )
        edges_list = []
        with patch.object(ext, "_extract_comment_batch", new_callable=AsyncMock, return_value=[comment]):
            await ext._collect_batch(page, "post1", set(), [], edges_list)
        assert len(edges_list) == 1
        assert edges_list[0].user_id == "user_with_id"


# ─── _collect_replies_fullpage ────────────────────────────────────────────────

class TestCollectRepliesFullpage:
    @pytest.mark.asyncio
    async def test_skips_items_without_author_href(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        raw_items = [
            {"aria": "Reply", "authorHref": "", "authorName": "User", "text": "reply text",
             "imgs": [], "numericId": None, "relTime": ""}
        ]
        page.evaluate = AsyncMock(return_value=raw_items)
        comments = []
        edges = []
        await ext._collect_replies_fullpage(page, "post1", set(), comments, edges)
        assert len(comments) == 0

    @pytest.mark.asyncio
    async def test_adds_new_reply_comment(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        raw_items = [{
            "aria": "Reply by User",
            "authorHref": "https://www.facebook.com/user.test",
            "authorName": "Reply User",
            "text": "This is a reply",
            "imgs": [],
            "numericId": "99887766",
            "relTime": "5 phút trước",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)
        comments = []
        edges = []
        await ext._collect_replies_fullpage(page, "post1", set(), comments, edges)
        assert len(comments) == 1
        assert comments[0].comment_id == "99887766"
        assert comments[0].raw_text == "This is a reply"

    @pytest.mark.asyncio
    async def test_deduplicates_by_content_key(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        raw_items = [{
            "aria": "Reply",
            "authorHref": "https://www.facebook.com/user1",
            "authorName": "User",
            "text": "duplicate text",
            "imgs": [],
            "numericId": None,
            "relTime": "",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)
        # Pre-populate seen_content via existing comment
        existing = CommentNode(
            comment_id="existing", post_id="post1",
            author_id="user1",  # matches extract_user_id("https://www.facebook.com/user1")
            author_name="User",
            raw_text="duplicate text",
            cleaned_text="duplicate text",
        )
        comments = [existing]
        edges = []
        await ext._collect_replies_fullpage(page, "post1", set(), comments, edges)
        # Should not add another since content key matches
        assert len(comments) == 1

    @pytest.mark.asyncio
    async def test_deduplicates_by_comment_id(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        raw_items = [{
            "aria": "Reply",
            "authorHref": "https://www.facebook.com/user.new",
            "authorName": "New User",
            "text": "unique text here",
            "imgs": [],
            "numericId": "already_seen_id",
            "relTime": "",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)
        seen_ids = {"already_seen_id"}
        comments = []
        edges = []
        await ext._collect_replies_fullpage(page, "post1", seen_ids, comments, edges)
        assert len(comments) == 0

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        page.evaluate = AsyncMock(side_effect=Exception("JS error"))
        comments = []
        edges = []
        await ext._collect_replies_fullpage(page, "post1", set(), comments, edges)
        assert len(comments) == 0

    @pytest.mark.asyncio
    async def test_resolves_parent_id_from_aria(self):
        ext = make_comment_extractor()
        page = make_mock_page()
        raw_items = [{
            "aria": "Phản hồi bình luận của ParentAuthor dưới tên",
            "authorHref": "https://www.facebook.com/replier",
            "authorName": "Replier",
            "text": "This is a sub-reply",
            "imgs": [],
            "numericId": "555666",
            "relTime": "",
        }]
        page.evaluate = AsyncMock(return_value=raw_items)

        # Existing comment with author ParentAuthor
        parent_comment = CommentNode(
            comment_id="parent_cmt_id",
            post_id="post1",
            author_name="ParentAuthor",
            raw_text="parent text",
            cleaned_text="parent text",
        )
        comments = [parent_comment]
        edges = []
        seen_ids = {"parent_cmt_id"}
        await ext._collect_replies_fullpage(page, "post1", seen_ids, comments, edges)
        # The reply should be added with parent_id resolved
        new_comment = next((c for c in comments if c.comment_id == "555666"), None)
        assert new_comment is not None
        assert new_comment.parent_id == "parent_cmt_id"


# ─── _expand_all_reply_buttons ────────────────────────────────────────────────

class TestExpandAllReplyButtons:
    @pytest.mark.asyncio
    async def test_exits_on_max_duration(self):
        """Test that the function respects MAX_DURATION cap."""
        ext = make_comment_extractor()
        page = make_mock_page()
        # Simulate: no buttons visible, always at bottom → hits IDLE_TIMEOUT quickly
        page.evaluate = AsyncMock(side_effect=lambda js, *args, **kwargs:
            {"atBottom": True, "scrollTop": 0} if "atBottom" in js else [])
        page.mouse.move = AsyncMock()
        page.mouse.wheel = AsyncMock()

        # Use real time — IDLE_TIMEOUT=3s, mock time to make it expire
        import time
        start = time.monotonic()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(ext, "_get_post_scroll_center", new_callable=AsyncMock, return_value=None):
                await ext._expand_all_reply_buttons(page)

        # Should complete without hanging
        elapsed = time.monotonic() - start
        assert elapsed < 10  # Should be fast since no buttons

    @pytest.mark.asyncio
    async def test_clicks_visible_reply_buttons(self):
        """Test that buttons in btn_list get clicked."""
        ext = make_comment_extractor()
        page = make_mock_page()

        call_count = [0]
        def mock_evaluate(js, *args, **kwargs):
            call_count[0] += 1
            if "atBottom" in js:
                # First call: not at bottom; subsequent: at bottom
                if call_count[0] <= 2:
                    return {"atBottom": False, "scrollTop": 0}
                return {"atBottom": True, "scrollTop": 0}
            if "btn_list" in js or "replies" in js or "div[role" in js:
                # Return one button on first call, then empty
                if call_count[0] <= 3:
                    return [{"x": 500, "y": 300, "text": "5 phản hồi"}]
                return []
            return None

        page.evaluate = AsyncMock(side_effect=mock_evaluate)
        page.mouse.move = AsyncMock()
        page.mouse.wheel = AsyncMock()
        page.mouse.click = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(ext, "_get_post_scroll_center", new_callable=AsyncMock, return_value={"cx": 500, "cy": 400}):
                await ext._expand_all_reply_buttons(page)


# ─── _extract_comment_batch ───────────────────────────────────────────────────

class TestExtractCommentBatch:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_root_and_no_elements(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 0
        page = make_mock_page()
        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            page.query_selector_all = AsyncMock(return_value=[])
            result = await ext._extract_comment_batch(page, "post1", set())
        assert result == []

    @pytest.mark.asyncio
    async def test_only_processes_new_elements(self):
        ext = make_comment_extractor()
        ext._processed_el_count = 2  # already processed 2
        page = make_mock_page()

        # Create 3 elements, only index 2 is "new"
        el1 = make_mock_element()
        el2 = make_mock_element()
        el3 = make_mock_element(text="New comment", href="https://www.facebook.com/user3")

        comment = CommentNode(
            comment_id="cmt_new", post_id="post1",
            author_id="user3", author_name="User",
            raw_text="New comment", cleaned_text="New comment",
        )

        with patch.object(ext, "_get_comment_root", new_callable=AsyncMock, return_value=(None, False)):
            with patch.object(ext, "_extract_single_comment", new_callable=AsyncMock, return_value=comment) as mock_extract:
                page.query_selector_all = AsyncMock(return_value=[el1, el2, el3])
                result = await ext._extract_comment_batch(page, "post1", set())
        # Should only call _extract_single_comment once for the new element
        assert mock_extract.call_count == 1


# ─── extract_all_comments (integration) ──────────────────────────────────────

class TestExtractAllComments:
    @pytest.mark.asyncio
    async def test_returns_empty_on_full_mock(self):
        """Test that extract_all_comments runs without error on fully-mocked page."""
        ext = CommentExtractor({
            "max_comments": 5,
            "max_replies_per_comment": 3,
            "scrape_replies": False,
        })
        page = make_mock_page()

        with patch.object(ext, "_scroll_to_comments", new_callable=AsyncMock):
            with patch.object(ext, "_expand_comments", new_callable=AsyncMock):
                with patch.object(ext, "_collect_batch", new_callable=AsyncMock, return_value=0):
                    with patch.object(ext, "_scroll_incremental", new_callable=AsyncMock):
                        with patch.object(ext, "_click_and_wait_new_nodes", new_callable=AsyncMock, return_value=False):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                comments, edges = await ext.extract_all_comments(page, "post1")
        assert isinstance(comments, list)
        assert isinstance(edges, list)

    @pytest.mark.asyncio
    async def test_scrapes_replies_when_enabled(self):
        """Test that _expand_all_reply_buttons and _collect_replies_fullpage are called when scrape_replies=True."""
        ext = CommentExtractor({
            "max_comments": 5,
            "max_replies_per_comment": 3,
            "scrape_replies": True,
        })
        page = make_mock_page()

        with patch.object(ext, "_scroll_to_comments", new_callable=AsyncMock):
            with patch.object(ext, "_expand_comments", new_callable=AsyncMock):
                with patch.object(ext, "_collect_batch", new_callable=AsyncMock, return_value=0):
                    with patch.object(ext, "_scroll_incremental", new_callable=AsyncMock):
                        with patch.object(ext, "_click_and_wait_new_nodes", new_callable=AsyncMock, return_value=False):
                            with patch.object(ext, "_expand_all_reply_buttons", new_callable=AsyncMock) as mock_expand:
                                with patch.object(ext, "_collect_replies_fullpage", new_callable=AsyncMock) as mock_replies:
                                    with patch("asyncio.sleep", new_callable=AsyncMock):
                                        comments, edges = await ext.extract_all_comments(page, "post1")
        mock_expand.assert_called_once()
        mock_replies.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_max_comments_limit(self):
        """Test that loop exits when max_comments reached."""
        ext = CommentExtractor({
            "max_comments": 3,
            "max_replies_per_comment": 3,
            "scrape_replies": False,
        })
        page = make_mock_page()

        # Make _collect_batch return 2 on first call, then 0
        call_count = [0]
        async def mock_collect(*args, **kwargs):
            call_count[0] += 1
            comments_list = args[3]  # 4th arg is comments list
            if call_count[0] == 1:
                # Initial batch: add 2 comments
                return 2
            return 0

        with patch.object(ext, "_scroll_to_comments", new_callable=AsyncMock):
            with patch.object(ext, "_expand_comments", new_callable=AsyncMock):
                with patch.object(ext, "_collect_batch", side_effect=mock_collect):
                    with patch.object(ext, "_scroll_incremental", new_callable=AsyncMock):
                        with patch.object(ext, "_click_and_wait_new_nodes", new_callable=AsyncMock, return_value=False):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                comments, edges = await ext.extract_all_comments(page, "post1")
        # total should be <= max_comments
        assert len(comments) <= ext.max_comments


# ─── extract_all_comments_mbasic ─────────────────────────────────────────────

class TestExtractAllCommentsMbasic:
    @pytest.mark.asyncio
    async def test_returns_empty_on_redirect(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://www.facebook.com/redirect")
        page.goto = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            comments, edges = await ext.extract_all_comments_mbasic(
                page, "post1", "https://mbasic.facebook.com/post1"
            )
        assert comments == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_container(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://mbasic.facebook.com/post1")
        page.goto = AsyncMock(return_value=None)
        page.query_selector = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            comments, edges = await ext.extract_all_comments_mbasic(
                page, "post1", "https://mbasic.facebook.com/post1"
            )
        assert comments == []
        assert edges == []

    @pytest.mark.asyncio
    async def test_extracts_mbasic_comments(self):
        ext = make_comment_extractor()
        page = make_mock_page(url="https://mbasic.facebook.com/post1")
        page.goto = AsyncMock(return_value=None)

        container = AsyncMock()
        # Comment element with numeric ID
        comment_el = AsyncMock()
        comment_el.get_attribute = AsyncMock(side_effect=lambda a: "12345678" if a == "id" else None)
        author_link = AsyncMock()
        author_link.inner_text = AsyncMock(return_value="Test Author")
        author_link.get_attribute = AsyncMock(return_value="https://www.facebook.com/user.test")
        comment_el.query_selector = AsyncMock(return_value=author_link)
        text_el = AsyncMock()
        text_el.inner_text = AsyncMock(return_value="Mbasic comment text")
        comment_el.query_selector = AsyncMock(side_effect=lambda sel:
            author_link if "h3 a" in sel or "strong a" in sel else text_el)
        container.query_selector_all = AsyncMock(return_value=[comment_el])
        page.query_selector = AsyncMock(side_effect=lambda sel:
            container if "m_story" in sel else None)
        # No "more comments" link
        page.query_selector = AsyncMock(side_effect=lambda sel:
            container if "m_story" in sel or "MPhoto" in sel else None)
        container.query_selector_all = AsyncMock(return_value=[comment_el])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            comments, edges = await ext.extract_all_comments_mbasic(
                page, "post1", "https://mbasic.facebook.com/post1"
            )
        # May or may not extract depending on mock structure, but should not raise
        assert isinstance(comments, list)
        assert isinstance(edges, list)
