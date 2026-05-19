"""
More tests for CommentExtractor uncovered methods:
- _find_comment_scope
- _scroll_to_comments (photo URL path)
- _expand_comments (with sort button)
- _get_comment_root
- _extract_comment_images
- _expand_comment_see_more
- _extract_replies
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.extractors.comment_extractor import CommentExtractor
from src.graph.schema import CommentNode


def make_page(url="https://www.facebook.com/PageWSS/posts/123"):
    page = AsyncMock()
    page.url = url
    page.goto = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=None)
    handle = AsyncMock()
    handle.as_element = MagicMock(return_value=None)
    page.evaluate_handle = AsyncMock(return_value=handle)
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    resp_ctx = AsyncMock()
    resp_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
    resp_ctx.__aexit__ = AsyncMock(return_value=False)
    page.expect_response = MagicMock(return_value=resp_ctx)
    return page


def make_ext():
    return CommentExtractor({
        "max_comments": 10,
        "max_replies_per_comment": 3,
        "scrape_replies": False,
    })


# ─── _find_comment_scope ──────────────────────────────────────────────────────

class TestFindCommentScope:
    @pytest.mark.asyncio
    async def test_returns_panel_when_photo_page(self):
        ext = make_ext()
        page = make_page()
        panel = AsyncMock()
        page.query_selector = AsyncMock(return_value=panel)
        result = await ext._find_comment_scope(page)
        assert result == panel

    @pytest.mark.asyncio
    async def test_returns_none_when_no_panel(self):
        ext = make_ext()
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        page.evaluate = AsyncMock(return_value=None)
        result = await ext._find_comment_scope(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_comment_input_found_but_no_parent(self):
        ext = make_ext()
        page = make_page()
        el = AsyncMock()
        call_count = [0]

        async def mock_qs(sel):
            call_count[0] += 1
            if "complementary" in sel:
                return None
            if "UFI" in sel or "Viết" in sel or "Write" in sel or "Comment" in sel:
                return el
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        page.evaluate = AsyncMock(return_value=None)  # parent lookup returns None
        result = await ext._find_comment_scope(page)
        assert result is None  # returns None (page fallback)


# ─── _scroll_to_comments ──────────────────────────────────────────────────────

class TestScrollToComments:
    @pytest.mark.asyncio
    async def test_scrolls_right_panel_for_photo(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/photo/?fbid=12345")
        panel = AsyncMock()
        page.query_selector = AsyncMock(return_value=panel)
        page.evaluate = AsyncMock(return_value=None)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._scroll_to_comments(page)
        page.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_uses_center_for_regular_post(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_get_post_scroll_center", new_callable=AsyncMock,
                          return_value={"cx": 500, "cy": 400}):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await ext._scroll_to_comments(page)
        page.mouse.move.assert_called_with(500, 400)

    @pytest.mark.asyncio
    async def test_falls_back_to_wheel_when_no_center(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.query_selector = AsyncMock(return_value=None)
        with patch.object(ext, "_get_post_scroll_center", new_callable=AsyncMock, return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await ext._scroll_to_comments(page)
        page.mouse.wheel.assert_called_with(0, 1500)

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self):
        ext = make_ext()
        page = make_page()
        page.query_selector = AsyncMock(side_effect=Exception("Error"))
        # Should not raise
        await ext._scroll_to_comments(page)


# ─── _expand_comments ────────────────────────────────────────────────────────

class TestExpandComments:
    @pytest.mark.asyncio
    async def test_clicks_sort_button(self):
        ext = make_ext()
        page = make_page()
        sort_btn = AsyncMock()
        sort_btn.scroll_into_view_if_needed = AsyncMock()
        sort_btn.click = AsyncMock()

        opt = AsyncMock()
        opt.is_visible = AsyncMock(return_value=True)
        opt.click = AsyncMock()

        opt_handle = AsyncMock()
        opt_handle.as_element = MagicMock(return_value=opt)
        page.evaluate_handle = AsyncMock(return_value=opt_handle)

        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "Phù hợp nhất" in sel or "Top comments" in sel:
                return sort_btn
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(ext, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
                await ext._expand_comments(page)
        sort_btn.click.assert_called()

    @pytest.mark.asyncio
    async def test_presses_escape_when_no_option(self):
        ext = make_ext()
        page = make_page()
        sort_btn = AsyncMock()
        sort_btn.scroll_into_view_if_needed = AsyncMock()
        sort_btn.click = AsyncMock()

        # No matching menu option
        opt_handle = AsyncMock()
        opt_handle.as_element = MagicMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=opt_handle)

        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "Phù hợp nhất" in sel:
                return sort_btn
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(ext, "_find_load_more_btn", new_callable=AsyncMock, return_value=None):
                await ext._expand_comments(page)
        page.keyboard.press.assert_called_with("Escape")

    @pytest.mark.asyncio
    async def test_preloads_batches_by_clicking_load_more(self):
        ext = make_ext()
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)  # No sort button

        load_more_btn = AsyncMock()
        load_more_btn.scroll_into_view_if_needed = AsyncMock()
        load_more_btn.click = AsyncMock()

        click_count = [0]
        async def mock_find_load_more(pg):
            click_count[0] += 1
            if click_count[0] <= 2:
                return load_more_btn
            return None

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(ext, "_find_load_more_btn", side_effect=mock_find_load_more):
                await ext._expand_comments(page)
        assert load_more_btn.click.call_count >= 2


# ─── _get_comment_root ────────────────────────────────────────────────────────

class TestGetCommentRoot:
    @pytest.mark.asyncio
    async def test_returns_panel_for_photo_url(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/photo/?fbid=12345")
        panel = AsyncMock()
        page.query_selector = AsyncMock(return_value=panel)
        root, is_photo = await ext._get_comment_root(page)
        assert root == panel
        assert is_photo is True

    @pytest.mark.asyncio
    async def test_returns_dialog_for_regular_url(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/PageWSS/posts/123")
        dialog = AsyncMock()
        call_count = [0]

        async def mock_qs(sel):
            call_count[0] += 1
            if "complementary" in sel:
                return None  # Not a photo URL
            if sel == "dialog":
                return dialog
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        root, is_photo = await ext._get_comment_root(page)
        assert root == dialog
        assert is_photo is False

    @pytest.mark.asyncio
    async def test_falls_back_to_container_el(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.query_selector = AsyncMock(return_value=None)  # No dialog either

        container = AsyncMock()
        handle = AsyncMock()
        handle.as_element = MagicMock(return_value=container)
        page.evaluate_handle = AsyncMock(return_value=handle)

        with patch.object(ext, "_get_post_container_el", new_callable=AsyncMock, return_value=handle):
            root, is_photo = await ext._get_comment_root(page)
        assert root == container

    @pytest.mark.asyncio
    async def test_falls_back_to_permalink_pagelet(self):
        ext = make_ext()
        page = make_page(url="https://www.facebook.com/PageWSS/posts/123")
        page.query_selector = AsyncMock(return_value=None)

        pagelet = AsyncMock()
        handle = AsyncMock()
        handle.as_element = MagicMock(return_value=None)
        page.evaluate_handle = AsyncMock(return_value=handle)

        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "PermalinkPostFeed" in sel or "PermalinkPost" in sel:
                return pagelet
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        with patch.object(ext, "_get_post_container_el", new_callable=AsyncMock, return_value=handle):
            root, is_photo = await ext._get_comment_root(page)
        assert root == pagelet


# ─── _extract_comment_images ──────────────────────────────────────────────────

class TestExtractCommentImages:
    @pytest.mark.asyncio
    async def test_returns_user_upload_images(self):
        ext = make_ext()
        el = AsyncMock()
        img = AsyncMock()
        img.get_attribute = AsyncMock(return_value="https://scontent.fbcdn.net/user_image.jpg")
        el.query_selector_all = AsyncMock(return_value=[img])
        result = await ext._extract_comment_images(el)
        assert "https://scontent.fbcdn.net/user_image.jpg" in result

    @pytest.mark.asyncio
    async def test_filters_emoji_images(self):
        ext = make_ext()
        el = AsyncMock()
        emoji_img = AsyncMock()
        emoji_img.get_attribute = AsyncMock(return_value="https://static.xx.fbcdn.net/emoji/e.png")
        el.query_selector_all = AsyncMock(return_value=[emoji_img])
        result = await ext._extract_comment_images(el)
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_rsrc_images(self):
        ext = make_ext()
        el = AsyncMock()
        rsrc_img = AsyncMock()
        rsrc_img.get_attribute = AsyncMock(return_value="https://static.fbcdn.net/rsrc.php/icon.png")
        el.query_selector_all = AsyncMock(return_value=[rsrc_img])
        result = await ext._extract_comment_images(el)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self):
        ext = make_ext()
        el = AsyncMock()
        el.query_selector_all = AsyncMock(side_effect=Exception("Error"))
        result = await ext._extract_comment_images(el)
        assert result == []


# ─── _expand_comment_see_more ────────────────────────────────────────────────

class TestExpandCommentSeeMore:
    @pytest.mark.asyncio
    async def test_clicks_see_more_button(self):
        ext = make_ext()
        el = AsyncMock()
        btn = AsyncMock()
        btn.evaluate = AsyncMock(return_value=None)
        el.query_selector = AsyncMock(return_value=btn)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await ext._expand_comment_see_more(el)
        btn.evaluate.assert_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_button(self):
        ext = make_ext()
        el = AsyncMock()
        el.query_selector = AsyncMock(return_value=None)
        # Should not raise
        await ext._expand_comment_see_more(el)


# ─── _extract_replies ─────────────────────────────────────────────────────────

class TestExtractReplies:
    @pytest.mark.asyncio
    async def test_returns_empty_when_exception(self):
        ext = make_ext()
        el = AsyncMock()
        el.evaluate = AsyncMock(side_effect=Exception("DOM error"))
        el.evaluate_handle = AsyncMock(side_effect=Exception("Error"))
        result = await ext._extract_replies(el, "post1", "parent_cmt", set())
        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_replies_from_parent(self):
        ext = make_ext()
        comment_el = AsyncMock()
        comment_el.evaluate = AsyncMock(return_value=None)  # No click needed

        parent_handle = AsyncMock()
        parent_el = AsyncMock()
        parent_handle.as_element = MagicMock(return_value=parent_el)
        comment_el.evaluate_handle = AsyncMock(return_value=parent_handle)

        reply_el = AsyncMock()
        reply_el.evaluate = AsyncMock(return_value=False)  # is_self = False
        parent_el.query_selector_all = AsyncMock(return_value=[reply_el])

        reply_comment = CommentNode(
            comment_id="reply_1", post_id="post1",
            author_id="user2", author_name="Replier",
            raw_text="Reply text", cleaned_text="Reply text",
            parent_id="parent_cmt", depth=1,
        )

        with patch.object(ext, "_extract_single_comment", new_callable=AsyncMock, return_value=reply_comment):
            result = await ext._extract_replies(comment_el, "post1", "parent_cmt", set())
        assert len(result) == 1
        assert result[0].depth == 1


# ─── _get_post_container_el ───────────────────────────────────────────────────

class TestGetPostContainerEl:
    @pytest.mark.asyncio
    async def test_returns_handle(self):
        ext = make_ext()
        page = make_page()
        handle = AsyncMock()
        page.evaluate_handle = AsyncMock(return_value=handle)
        result = await ext._get_post_container_el(page)
        assert result == handle


# ─── _get_dialog_scroll_container ────────────────────────────────────────────

class TestGetDialogScrollContainer:
    @pytest.mark.asyncio
    async def test_returns_handle(self):
        ext = make_ext()
        page = make_page()
        handle = AsyncMock()
        page.evaluate_handle = AsyncMock(return_value=handle)
        result = await ext._get_dialog_scroll_container(page)
        assert result == handle
