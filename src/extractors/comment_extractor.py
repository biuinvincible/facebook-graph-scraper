"""
Comment tree extractor - builds hierarchical comment graph.
Handles expand-all, load-more, nested replies.
"""
import asyncio
import re
import uuid
from typing import List, Dict, Any, Optional
from playwright.async_api import Page, ElementHandle
from loguru import logger

from ..graph.schema import CommentNode, UserCommentEdge
from ..utils.helpers import (
    extract_user_id, extract_hashtags, extract_mentions,
    extract_emojis, clean_text, parse_count
)


class CommentExtractor:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.max_comments = config.get("max_comments", 500)
        self.max_replies = config.get("max_replies_per_comment", 50)
        self.scrape_replies = config.get("scrape_replies", True)

    async def extract_all_comments_mbasic(
        self, page: Page, post_id: str, mbasic_url: str
    ) -> tuple[List[CommentNode], List[UserCommentEdge]]:
        """
        Extract comments từ mbasic.facebook.com — clean HTML, không có related posts.
        mbasic có #m_story_permalink_view container chứa đúng post + comments của nó.
        Comment elements: div với id là số nguyên (comment ID).
        """
        comments: List[CommentNode] = []
        edges: List[UserCommentEdge] = []
        seen_ids = set()

        try:
            await page.goto(mbasic_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Kiểm tra mbasic có load không (bị redirect = không hoạt động)
            if "mbasic.facebook.com" not in page.url and "m.facebook.com" not in page.url:
                logger.warning(f"mbasic redirect detected — falling back to full site")
                return [], []

            container = await page.query_selector('#m_story_permalink_view, #MPhotoContent')
            if not container:
                return [], []

            # Paginate qua tối đa 10 trang "See More Comments"
            for _ in range(10):
                if len(comments) >= self.max_comments:
                    break

                # Comments trong mbasic: div hoặc table với id = số nguyên
                comment_els = await container.query_selector_all(
                    'div[id]:not([class*="story"]), '
                    '[data-sigil="comment"]'
                )
                for el in comment_els:
                    cid = await el.get_attribute("id") or ""
                    if not cid.isdigit():
                        continue
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)

                    # Author
                    author_link = await el.query_selector('h3 a, strong a')
                    author_name = author_text = ""
                    author_id = None
                    if author_link:
                        author_name = (await author_link.inner_text()).strip()
                        href = await author_link.get_attribute("href") or ""
                        from ..utils.helpers import extract_user_id
                        author_id = extract_user_id(href)

                    # Text
                    text_el = await el.query_selector('div[data-sigil="comment-body"], div > div')
                    raw_text = ""
                    if text_el:
                        raw_text = (await text_el.inner_text()).strip()
                    if not raw_text:
                        continue

                    from ..graph.schema import CommentNode as CN
                    comment = CN(
                        comment_id=cid,
                        post_id=post_id,
                        author_id=author_id,
                        author_name=author_name,
                        raw_text=raw_text,
                        cleaned_text=clean_text(raw_text),
                        hashtags=extract_hashtags(raw_text),
                        mentions=extract_mentions(raw_text),
                        emojis=extract_emojis(raw_text),
                    )
                    comments.append(comment)
                    if author_id:
                        edges.append(UserCommentEdge(
                            user_id=author_id,
                            comment_id=cid,
                            relation_type="author",
                        ))

                # "See More Comments" pagination
                more_link = await page.query_selector(
                    'a[href*="comment_tracking"]:has-text("comments"), '
                    'a:has-text("See More Comments"), '
                    'a:has-text("Xem thêm bình luận")'
                )
                if more_link:
                    await more_link.click()
                    await asyncio.sleep(1.5)
                    container = await page.query_selector('#m_story_permalink_view, #MPhotoContent')
                    if not container:
                        break
                else:
                    break

        except Exception as e:
            logger.warning(f"mbasic comment extraction failed: {e}")

        logger.info(f"mbasic extracted {len(comments)} comments for {post_id}")
        return comments, edges

    async def extract_all_comments(
        self, page: Page, post_id: str
    ) -> tuple[List[CommentNode], List[UserCommentEdge]]:
        """
        Extract all comments. Strategy (từ research):
        - Mechanism: button-click, không phải infinite scroll
        - Virtualization: extract TRƯỚC khi scroll khỏi comment đó
        - Wait: intercept GraphQL response thay vì fixed sleep
        - Scroll: incremental 400px/400ms (nhanh hơn bị FB throttle)
        """
        comments: List[CommentNode] = []
        edges: List[UserCommentEdge] = []
        seen_ids = set()
        total = 0
        no_new_streak = 0
        self._processed_el_count = 0  # chỉ process elements mới thêm vào DOM

        # Scroll đến comment section trước để sort button vào viewport
        await self._scroll_to_comments(page)

        # Click "Tất cả bình luận" ngay sau khi comment section visible
        await self._expand_comments(page)

        # Sau sort change, DOM rebuild → reset counter để không bỏ sót
        self._processed_el_count = 0
        await asyncio.sleep(2)  # chờ comments reload sau sort change

        # Extract batch đầu
        total += await self._collect_batch(page, post_id, seen_ids, comments, edges)

        for _ in range(100):
            if total >= self.max_comments:
                break

            # Scroll nhỏ hơn để không overshoot qua comments
            scroll_steps = 1 if no_new_streak > 0 else 2
            await self._scroll_incremental(page, px=350, steps=scroll_steps, delay=0.35)

            # Khi streak empty, scroll mạnh hơn xuống cuối
            if no_new_streak == 1:
                center = await self._get_post_scroll_center(page)
                if center:
                    await page.mouse.move(center['cx'], center['cy'])
                    for _ in range(5):
                        await page.mouse.wheel(0, 800)
                        await asyncio.sleep(0.2)
                else:
                    await page.mouse.wheel(0, 3000)
                await asyncio.sleep(0.8)

            # Click "Xem thêm bình luận" + đợi GraphQL response
            loaded = await self._click_and_wait_new_nodes(page)

            if not loaded:
                await self._scroll_incremental(page, px=400, steps=1, delay=0.3)

            new = await self._collect_batch(page, post_id, seen_ids, comments, edges)
            total += new

            if new == 0:
                no_new_streak += 1
                if no_new_streak >= 12:  # 12 empty iterations
                    break
                # Chờ lâu hơn khi streak để comments có thời gian load
                await asyncio.sleep(0.5 if no_new_streak < 4 else 1.0)
            else:
                no_new_streak = 0

        # Expand replies + scroll lại từ đầu để collect
        if self.scrape_replies:
            await self._expand_all_reply_buttons(page)
            await asyncio.sleep(2)
            # Scroll về đầu comment section
            await self._scroll_to_comments(page)
            await asyncio.sleep(1)
            # Reset và scroll lại để pick up replies đã load
            self._processed_el_count = 0
            no_new_streak_r = 0
            for _ in range(40):
                if len(comments) >= self.max_comments:
                    break
                await self._scroll_incremental(page, px=300, steps=1, delay=0.3)
                new_r = await self._collect_batch(page, post_id, seen_ids, comments, edges)
                if new_r == 0:
                    no_new_streak_r += 1
                    if no_new_streak_r >= 5:
                        break
                else:
                    no_new_streak_r = 0
            # Final pass trên full page cho replies là portals
            await self._collect_replies_fullpage(page, post_id, seen_ids, comments, edges)

        logger.info(f"Extracted {len(comments)} comments for post {post_id}")
        return comments, edges

    async def _collect_replies_fullpage(
        self, page: Page, post_id: str, seen_ids: set,
        comments: list, edges: list
    ):
        """
        Sau khi expand tất cả reply buttons, collect replies trên full page.
        Replies render như React portals ngoài foreground container → không dùng scoped root.
        Chỉ lấy elements chưa có trong seen_ids để tránh duplicate.
        """
        REPLY_SELS = (
            'div[aria-label*="Bình luận dưới tên"], '
            'div[aria-label*="Phản hồi bình luận của"], '
            'div[aria-label*="Phản hồi của"], '
            'div[aria-label*="Comment by"], '
            'div[aria-label*="Reply by"], '
            'div[aria-label*="Replied to"]'
        )
        try:
            all_els = await page.query_selector_all(REPLY_SELS)
            new_count = 0
            skip_count = 0
            for el in all_els:
                try:
                    comment = await self._extract_single_comment(el, post_id, None)
                    if comment and comment.comment_id not in seen_ids:
                        seen_ids.add(comment.comment_id)
                        comments.append(comment)
                        new_count += 1
                        if comment.author_id:
                            edges.append(UserCommentEdge(
                                user_id=comment.author_id,
                                comment_id=comment.comment_id,
                                relation_type="author",
                                timestamp=comment.timestamp,
                            ))
                    else:
                        skip_count += 1
                except Exception:
                    skip_count += 1
                    continue
            logger.debug(f"collect_replies_fullpage: {len(all_els)} els, +{new_count} new, {skip_count} skipped/fail")
        except Exception as e:
            logger.debug(f"collect_replies_fullpage error: {e}")

    async def _expand_all_reply_buttons(self, page: Page):
        """
        Click từng 'Xem X phản hồi' button bằng cách scroll từng comment vào viewport
        trước khi click. Cần thiết vì Facebook chỉ fetch data cho comments đang visible
        trong custom scroll viewport (data-thumb container).
        """
        center = await self._get_post_scroll_center(page)

        # Scroll dần và click reply buttons từng bước
        for _ in range(80):  # tối đa 80 scroll steps
            # Tìm và click button "Xem X phản hồi" hiện visible trong viewport
            clicked = await page.evaluate("""() => {
                let count = 0;
                for (const btn of document.querySelectorAll('div[role="button"]')) {
                    const t = btn.innerText ? btn.innerText.trim() : '';
                    if (!t) continue;
                    const hasReplyWord = t.includes('phản hồi') || t.includes('replies');
                    const hasNumber = /[0-9]/.test(t) || t.includes('thêm') || t.toLowerCase().includes('more');
                    const isHide = t.includes('Ẩn') || t.toLowerCase().includes('hide');
                    if (!hasReplyWord || !hasNumber || isHide) continue;
                    // Chỉ click nếu button đang trong viewport (visible)
                    const r = btn.getBoundingClientRect();
                    if (r.top >= 0 && r.bottom <= window.innerHeight) {
                        btn.click();
                        count++;
                    }
                }
                return count;
            }""")

            if clicked > 0:
                await asyncio.sleep(1.5)  # chờ replies load

            # Scroll thêm xuống dưới để reveal comments tiếp theo
            if center:
                await page.mouse.move(center['cx'], center['cy'])
                await page.mouse.wheel(0, 300)
            else:
                await page.mouse.wheel(0, 300)
            await asyncio.sleep(0.4)

            # Kiểm tra đã scroll đến cuối chưa
            at_bottom = await page.evaluate("""() => {
                const thumbs = [...document.querySelectorAll('[data-thumb]')];
                let best = null, bestH = 0;
                for (const t of thumbs) {
                    const h = parseFloat(t.style.height || '0');
                    if (h > bestH) { bestH = h; best = t; }
                }
                if (!best) return true;
                const p = best.parentElement;
                return !p || Math.abs(p.scrollTop + p.clientHeight - p.scrollHeight) < 20;
            }""")
            if at_bottom:
                # Một lần nữa sau khi ở cuối để đảm bảo
                await page.evaluate("""() => {
                    for (const btn of document.querySelectorAll('div[role="button"]')) {
                        const t = btn.innerText ? btn.innerText.trim() : '';
                        const hasReplyWord = t.includes('phản hồi') || t.includes('replies');
                        const hasNumber = /[0-9]/.test(t) || t.includes('thêm');
                        const isHide = t.includes('Ẩn') || t.toLowerCase().includes('hide');
                        if (hasReplyWord && hasNumber && !isHide) btn.click();
                    }
                }""")
                await asyncio.sleep(2)
                break

    async def _collect_batch(
        self, page: Page, post_id: str, seen_ids: set,
        comments: list, edges: list
    ) -> int:
        """Extract visible comments, add new ones to collections. Return new count."""
        batch = await self._extract_comment_batch(page, post_id, seen_ids)
        new_count = 0
        for comment in batch:
            if comment.comment_id not in seen_ids:
                seen_ids.add(comment.comment_id)
                comments.append(comment)
                new_count += 1
                if comment.author_id:
                    edges.append(UserCommentEdge(
                        user_id=comment.author_id,
                        comment_id=comment.comment_id,
                        relation_type="author",
                        timestamp=comment.timestamp,
                    ))
        return new_count

    def _reset_processed_count(self):
        self._processed_el_count = 0

    async def _get_post_scroll_center(self, page: Page):
        """
        FB dùng custom scroll (data-thumb), không phải native overflow scroll.
        Tìm scroll container của post qua [data-thumb] có height lớn nhất → parent của nó.
        Trả về (cx, cy) để mouse.wheel() đúng chỗ.
        """
        return await page.evaluate("""() => {
            const thumbs = [...document.querySelectorAll('[data-thumb]')];
            let best = null, bestH = 0;
            for (const t of thumbs) {
                const h = parseFloat(t.style.height || '0');
                if (h > bestH) { bestH = h; best = t; }
            }
            if (!best || bestH < 200) return null;
            const r = best.parentElement.getBoundingClientRect();
            if (r.width < 100 || r.height < 100) return null;
            return { cx: r.left + (r.width - 20) / 2, cy: r.top + r.height / 2 };
        }""")

    async def _get_post_container_el(self, page: Page):
        """
        Trả về ElementHandle của foreground post container (parent của data-thumb lớn nhất).
        Dùng để scope comment extraction, tránh lấy nhầm từ background news feed.
        """
        return await page.evaluate_handle("""() => {
            const thumbs = [...document.querySelectorAll('[data-thumb]')];
            let best = null, bestH = 0;
            for (const t of thumbs) {
                const h = parseFloat(t.style.height || '0');
                if (h > bestH) { bestH = h; best = t; }
            }
            if (!best || bestH < 200) return null;
            const parent = best.parentElement;
            const r = parent.getBoundingClientRect();
            if (r.width < 100 || r.height < 100) return null;
            return parent;
        }""")

    async def _scroll_incremental(self, page: Page, px: int = 400, steps: int = 2, delay: float = 0.35):
        """Scroll đúng container: photo panel hoặc post custom scroll (data-thumb)."""
        current_url = page.url
        is_photo_url = '/photo/' in current_url or ('fbid=' in current_url and '/posts/' not in current_url)
        for _ in range(steps):
            if is_photo_url:
                panel = await page.query_selector('[role="complementary"]')
                if panel:
                    await panel.evaluate("(el, px) => el.scrollBy(0, px)", px)
                    await asyncio.sleep(delay)
                    continue
            # Regular post: dùng data-thumb để tìm vị trí, move mouse, wheel
            center = await self._get_post_scroll_center(page)
            if center:
                await page.mouse.move(center['cx'], center['cy'])
                await page.mouse.wheel(0, px)
            else:
                # Fallback
                await page.mouse.wheel(0, px)
            await asyncio.sleep(delay)

    async def _click_and_wait_new_nodes(self, page: Page) -> bool:
        """
        Click 'Xem thêm bình luận' + intercept GraphQL response.
        "False positive" (background analytics) có lợi: proceed nhanh, iteration
        tiếp theo extract comments tiếp theo. Nhanh hơn MutationObserver polling.
        """
        btn = await self._find_load_more_btn(page)
        if not btn:
            return False
        try:
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.15)
            async with page.expect_response(
                lambda r: "graphql" in r.url and r.request.method == "POST",
                timeout=5000,
            ):
                await btn.click()
            return True
        except Exception:
            return True  # Timeout hoặc stale — đã click rồi

    async def _find_load_more_btn(self, page: Page):
        """Tìm button 'Xem thêm bình luận' — thử trong scoped root trước, rồi toàn trang"""
        selectors = [
            'div[role="button"]:has-text("Xem thêm bình luận")',
            'div[role="button"]:has-text("View more comments")',
            'div[role="button"]:has-text("Xem thêm phản hồi")',
            'div[role="button"]:has-text("View more replies")',
        ]
        scoped_root, _ = await self._get_comment_root(page)
        for root in ([scoped_root, page] if scoped_root else [page]):
            if root is None:
                continue
            for sel in selectors:
                try:
                    btn = await root.query_selector(sel)
                    if btn and await btn.is_visible():
                        return btn
                except Exception:
                    continue
        return None

    async def _find_comment_scope(self, page: Page):
        """
        Tìm container chứa comments của post chính.
        Tránh lấy comments từ related posts bên dưới trang.
        """
        # Photo viewer: right panel
        panel = await page.query_selector('[role="complementary"]')
        if panel:
            return panel

        # Permalink page: tìm comment input area — comments luôn ngay trên input
        # Tìm container wrap cả "Viết bình luận" input
        for sel in [
            '[data-pagelet*="UFI"]',
            '[aria-label*="Viết bình luận"]',
            '[aria-label*="Write a comment"]',
            '[aria-label*="Comment"]',
        ]:
            el = await page.query_selector(sel)
            if el:
                # Lấy parent container bao gồm cả comments + input
                parent = await page.evaluate("""el => {
                    // Leo lên 3-5 cấp để lấy container đủ rộng
                    let p = el;
                    for (let i = 0; i < 5; i++) {
                        if (!p.parentElement) break;
                        p = p.parentElement;
                        if (p.querySelectorAll('ul > li').length > 0) return null; // đã có comments
                    }
                    return null;
                }""", el)
                # Trả về page nếu không tìm được parent tốt
                return None

        return None  # fallback: toàn page

    async def _scroll_to_comments(self, page: Page):
        """Scroll đến comment section"""
        try:
            # Photo viewer: scroll right panel
            current_url = page.url
            is_photo_url = '/photo/' in current_url or ('fbid=' in current_url and '/posts/' not in current_url)
            right_panel = await page.query_selector('[role="complementary"]') if is_photo_url else None
            if right_panel:
                await page.evaluate(
                    "el => el.scrollTo(0, el.scrollHeight * 0.3)", right_panel
                )
                await asyncio.sleep(1)
                return

            # Regular post: scroll custom container xuống 40% để reveal comments
            center = await self._get_post_scroll_center(page)
            if center:
                await page.mouse.move(center['cx'], center['cy'])
                for _ in range(4):
                    await page.mouse.wheel(0, 500)
                    await asyncio.sleep(0.3)
            else:
                await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1)
        except Exception:
            pass

    async def _expand_comments(self, page: Page):
        """Click sort để hiện TẤT CẢ bình luận, rồi pre-load vài batch đầu"""
        # Sort → "Tất cả bình luận" hoặc "Mới nhất"
        for sort_sel in [
            'div[role="button"]:has-text("Phù hợp nhất")',
            'div[role="button"]:has-text("Bình luận nổi bật")',
            'div[role="button"]:has-text("Top comments")',
            '[aria-label*="Sort comments"]',
        ]:
            try:
                btn = await page.query_selector(sort_sel)
                if not btn:
                    continue
                await btn.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await btn.click()
                await asyncio.sleep(1.5)  # chờ menu render

                # Dùng JS để match TITLE (dòng đầu) của menuitem, tránh match nhầm description
                # "Mới nhất" có description chứa "tất cả bình luận" → has-text nhầm
                opt_handle = await page.evaluate_handle("""() => {
                    const titles = ['Tất cả bình luận', 'All comments'];
                    for (const el of document.querySelectorAll('[role="menuitem"]')) {
                        const firstLine = el.innerText.split('\\n')[0].trim();
                        if (titles.some(t => firstLine.toLowerCase() === t.toLowerCase())) {
                            return el;
                        }
                    }
                    return null;
                }""")
                opt = opt_handle.as_element()

                if opt and await opt.is_visible():
                    await opt.click()
                    await asyncio.sleep(2)
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                break
            except Exception:
                continue

        # Pre-load vài batch đầu
        for _ in range(3):
            btn = await self._find_load_more_btn(page)
            if not btn:
                break
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await asyncio.sleep(1.5)
            except Exception:
                break

    async def _get_dialog_scroll_container(self, page: Page):
        """
        Regular posts mở như dialog overlay trên FB.
        Container scroll là div bên trong [dialog] có overflow auto/scroll.
        """
        return await page.evaluate_handle("""() => {
            const dialog = document.querySelector('dialog');
            if (!dialog) return null;
            for (const el of dialog.querySelectorAll('div')) {
                const ov = getComputedStyle(el).overflow + getComputedStyle(el).overflowY;
                if ((ov.indexOf('scroll') >= 0 || ov.indexOf('auto') >= 0)
                    && el.scrollHeight > el.clientHeight + 50) {
                    return el;
                }
            }
            return null;
        }""")

    async def _get_comment_root(self, page: Page):
        """
        Trả về container để scope comment extraction.
        - Photo viewer: [role="complementary"] (right panel)
        - Regular post dialog: [dialog] overlay container
        """
        current_url = page.url
        is_photo_url = '/photo/' in current_url or ('fbid=' in current_url and '/posts/' not in current_url)

        # Photo viewer
        if is_photo_url:
            panel = await page.query_selector('[role="complementary"]')
            if panel:
                return panel, True

        # Regular post dialog overlay — dùng HTML <dialog> element tag
        dialog = await page.query_selector('dialog')
        if dialog:
            return dialog, False

        # Foreground post overlay: dùng data-thumb container để tránh lấy nhầm background feed
        # Đây là trường hợp post mở đè lên news feed của 1 page/account khác
        container_handle = await self._get_post_container_el(page)
        container = container_handle.as_element() if container_handle else None
        if container:
            return container, False

        # Fallback: permalink pagelets
        for sel in [
            '[data-pagelet="PermalinkPostFeed"]',
            '[data-pagelet*="PermalinkPost"]',
        ]:
            el = await page.query_selector(sel)
            if el:
                return el, False

        return None, False

    async def _extract_comment_batch(
        self, page: Page, post_id: str, seen_ids: set
    ) -> List[CommentNode]:
        """
        Extract comment elements — chỉ process elements MỚI.
        Scope vào comment section của post chính (không lấy comments từ related posts).
        """
        comments = []
        try:
            root, is_photo = await self._get_comment_root(page)

            COMMENT_SELS = (
                'div[aria-label*="Comment by"], '
                'div[aria-label*="Bình luận của"], '
                'div[aria-label*="Bình luận dưới tên"], '
                'div[aria-label*="Phản hồi bình luận của"], '
                'div[aria-label*="Phản hồi của"], '
                'div[aria-label*="Reply by"], '
                'div[aria-label*="Replied to"], '
                'ul > li div[role="article"]'
            )

            if root:
                all_els = await root.query_selector_all(COMMENT_SELS)
            else:
                all_els = []

            # Full page fallback nếu không tìm được root hoặc root rỗng
            if not all_els:
                all_els = await page.query_selector_all(COMMENT_SELS)
            if not all_els:
                all_els = await page.query_selector_all(
                    'div[role="article"]:not([data-pagelet])'
                )

            # Chỉ process elements CHƯA process — FB append mới vào cuối
            prev_count = getattr(self, '_processed_el_count', 0)
            if len(all_els) < prev_count:
                prev_count = 0
            new_els = all_els[prev_count:]
            self._processed_el_count = len(all_els)

            for el in new_els:
                try:
                    comment = await self._extract_single_comment(el, post_id, None)
                    if comment and comment.comment_id not in seen_ids:
                        comments.append(comment)

                        # Extract replies if enabled
                        if self.scrape_replies:
                            replies = await self._extract_replies(el, post_id, comment.comment_id, seen_ids)
                            comments.extend(replies)
                except Exception as e:
                    logger.debug(f"Comment extraction error: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Batch comment extraction error: {e}")

        return comments

    async def _expand_comment_see_more(self, el: ElementHandle):
        """Click 'Xem thêm'/'See more' bên trong comment để lấy full text"""
        for sel in [
            'div[role="button"]:has-text("Xem thêm")',
            'span[role="button"]:has-text("Xem thêm")',
            'div[role="button"]:has-text("See more")',
            'span[role="button"]:has-text("See more")',
        ]:
            try:
                btn = await el.query_selector(sel)
                if btn:
                    # Dùng JS click — element có thể không visible trong custom scroll viewport
                    await btn.evaluate("el => el.click()")
                    await asyncio.sleep(0.3)
                    return
            except Exception:
                continue

    async def _extract_single_comment(
        self, el: ElementHandle, post_id: str, parent_id: Optional[str]
    ) -> Optional[CommentNode]:
        try:
            # Click "Xem thêm" trước để expand full text nếu bị cắt
            await self._expand_comment_see_more(el)

            # Use JS to properly separate author name from comment text.
            # dir="auto" divs inside <a> tags = author name; outside = comment body.
            result = await el.evaluate("""el => {
                // Traverse DOM: text nodes + img[alt] để capture emoji
                function g(n) {
                    let r = '';
                    for (const c of n.childNodes) {
                        if (c.nodeType === 3) r += c.textContent;
                        else if (c.nodeType === 1) {
                            if (c.tagName === 'IMG') r += c.getAttribute('alt') || '';
                            else r += g(c);
                        }
                    }
                    return r;
                }

                let authorName = '', authorHref = '', text = '';

                // Author: MasuRii selectors
                const authorSelectors = [
                    'span > a[role="link"] > span > span[dir="auto"]',
                    'a[href*="/user/"] span',
                    'a[href*="/profile.php"] span',
                    'a[role="link"][href]',
                    'a[href]',
                ];
                for (const sel of authorSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.innerText.trim()) {
                        authorName = el2.innerText.trim();
                        const link = el2.closest('a') || el2;
                        authorHref = link.href || link.getAttribute('href') || '';
                        break;
                    }
                }

                // Comment text: stable selectors từ MasuRii
                const textSelectors = [
                    'div[data-ad-preview="message"] > span',
                    'div[data-ad-comet-preview="message"]',
                    'div[dir="auto"][style*="text-align: start"]',
                ];
                for (const sel of textSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.innerText.trim()) {
                        text = g(el2).trim();
                        break;
                    }
                }
                if (!text) {
                    const dirs = el.querySelectorAll('[dir="auto"]');
                    for (const d of dirs) {
                        if (d.closest('a')) continue;
                        const t = g(d).trim();
                        if (t && t !== authorName) { text = t; break; }
                    }
                }

                // Mention links: FB renders @mention thành <a href> bên trong [dir="auto"]
                // Phải query TẤT CẢ [dir="auto"], không chỉ cái đầu tiên
                const mentionedUsers = [];
                const allDirs = el.querySelectorAll('[dir="auto"]');
                allDirs.forEach(d => {
                    if (d.closest('a')) return;
                    d.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href || a.getAttribute('href') || '';
                        const name = a.innerText.trim();
                        // Profile link: có facebook.com/username, không phải post/photo/hashtag
                        if (name && href &&
                            href.includes('facebook.com/') &&
                            !href.includes('/photo') &&
                            !href.includes('/posts') &&
                            !href.includes('/groups') &&
                            !href.includes('/hashtag/') &&
                            !href.includes('/#') &&
                            !href.includes('l.facebook.com') &&   // external link wrapper
                            !href.includes('facebook.com/l.php') && // another wrapper
                            name !== authorName &&
                            !mentionedUsers.some(m => m.href === href)) {
                            mentionedUsers.push({ name, href });
                        }
                    });
                });

                // Like count — button có thể là sibling của article, tìm trong parent <li>
                let likeCount = 0;
                const likeRoot = el.closest('li') || el;
                const likeEl = likeRoot.querySelector(
                    '[aria-label*="cảm xúc"], [aria-label*="reaction"]'
                );
                if (likeEl) {
                    const likeLabel = likeEl.getAttribute('aria-label') || '';
                    const likeMatch = likeLabel.match(/^([0-9,.]+[kKmM]?) /);
                    if (likeMatch) {
                        const n = likeMatch[1].replace(/,/g,'');
                        likeCount = n.toLowerCase().endsWith('k')
                            ? Math.round(parseFloat(n)*1000)
                            : parseInt(n) || 0;
                    }
                }

                return { authorName, authorHref, text, mentionedUsers, likeCount };
            }""")

            raw_text = result.get("text", "").strip()
            author_name = result.get("authorName", "").strip()
            author_href = result.get("authorHref", "")
            mentioned_users = result.get("mentionedUsers", [])

            if not raw_text and not mentioned_users:
                return None

            # Lọc Facebook UI elements bị nhầm là comment (vd: "Tìm bạn bè", "Gợi ý cho bạn")
            _UI_NOISE_AUTHORS = {
                'Tìm bạn bè', 'Find friends', 'Gợi ý cho bạn', 'Suggested for you',
                'Bạn có thể biết', 'People you may know',
            }
            _UI_NOISE_TEXTS = {
                'Không còn bài viết nào', 'No more posts', 'No more content',
            }
            if author_name in _UI_NOISE_AUTHORS or raw_text in _UI_NOISE_TEXTS:
                return None
            # author_href phải là profile hợp lệ (có facebook.com/ path)
            if author_href and 'facebook.com/' not in author_href:
                return None

            author_id = extract_user_id(author_href) if author_href else None

            # Timestamp
            timestamp = await self._extract_comment_timestamp(el)

            # Likes — dùng giá trị từ JS (đã extract cùng lúc với text/author)
            like_count = result.get("likeCount", 0)
            if not like_count:
                like_count = await self._extract_comment_likes(el)

            # Images in comment
            image_urls = await self._extract_comment_images(el)

            # Generate stable comment ID
            comment_id = await self._get_comment_id(el) or f"cmt_{uuid.uuid4().hex[:12]}"

            depth = 1 if parent_id else 0

            return CommentNode(
                comment_id=comment_id,
                post_id=post_id,
                parent_id=parent_id,
                depth=depth,
                author_id=author_id,
                author_name=author_name,
                raw_text=raw_text,
                cleaned_text=clean_text(raw_text),
                hashtags=extract_hashtags(raw_text),
                mentions=extract_mentions(raw_text),
                emojis=extract_emojis(raw_text),
                image_urls=image_urls,
                like_count=like_count,
                timestamp=timestamp,
                mentioned_users=mentioned_users,
            )
        except Exception as e:
            logger.debug(f"Single comment extraction error: {e}")
            return None

    async def _extract_replies(
        self, comment_el: ElementHandle, post_id: str,
        parent_comment_id: str, seen_ids: set
    ) -> List[CommentNode]:
        """
        Click 'Xem X phản hồi' và extract reply comments.
        Button nằm NGOÀI comment article (là sibling) → tìm trong parent.
        """
        replies = []
        try:
            # Lấy parent container (button "Xem X phản hồi" là sibling của article)
            parent_handle = await comment_el.evaluate_handle("el => el.parentElement")
            parent_el = parent_handle.as_element()
            search_root = parent_el if parent_el else comment_el

            # Click "Xem X phản hồi" / "See X replies" tối đa 5 lần
            # Button là span[dir="auto"] trong sibling ngay sau comment_el
            for _ in range(5):
                clicked = await comment_el.evaluate("""(commentEl) => {
                    // Tìm trong siblings NGAY SAU comment article (không tìm trước nó)
                    // để đảm bảo đây là phản hồi của đúng comment này
                    const keywords = ['phản hồi', 'replies', 'Replies'];
                    let sibling = commentEl.nextElementSibling;
                    let tries = 0;
                    while (sibling && tries < 5) {
                        tries++;
                        // Nếu gặp comment article khác thì dừng
                        if (sibling.getAttribute && sibling.getAttribute('aria-label') &&
                            (sibling.getAttribute('aria-label').includes('Bình luận') ||
                             sibling.getAttribute('aria-label').includes('Comment'))) {
                            break;
                        }
                        // Tìm span chứa text phản hồi trong sibling này
                        const allSpans = sibling.querySelectorAll('span, div');
                        for (const el of allSpans) {
                            const t = el.innerText ? el.innerText.trim() : '';
                            if (!t) continue;
                            const matched = keywords.some(k => t.includes(k));
                            if (matched && (/[0-9]/.test(t) || t.includes('thêm') || t.toLowerCase().includes('more'))) {
                                // Leo lên tìm ancestor clickable
                                let p = el;
                                for (let i = 0; i < 8; i++) {
                                    if (!p || p === document.body) break;
                                    const role = p.getAttribute ? p.getAttribute('role') : null;
                                    const tabidx = p.getAttribute ? p.getAttribute('tabindex') : null;
                                    if (role === 'button' || tabidx !== null || p.tagName === 'BUTTON') {
                                        p.click();
                                        return t;
                                    }
                                    p = p.parentElement;
                                }
                                el.click();
                                return t;
                            }
                        }
                        sibling = sibling.nextElementSibling;
                    }
                    return null;
                }""")

                if clicked:
                    await asyncio.sleep(1.5)
                else:
                    break

            # Reply articles: tìm trong search_root (parent) nhưng exclude comment_el itself
            # Replies có aria-label "Bình luận dưới tên" giống top-level comments
            reply_els = await search_root.query_selector_all(
                'div[aria-label*="Bình luận dưới tên"], '
                'ul > li > div[role="article"]'
            )
            # Lọc: chỉ lấy elements KHÔNG phải chính comment_el
            actual_replies = []
            for el in reply_els:
                is_self = await el.evaluate(
                    "(el, art) => el === art",
                    comment_el
                )
                if not is_self:
                    actual_replies.append(el)

            for el in actual_replies[:self.max_replies]:
                if len(replies) >= self.max_replies:
                    break
                try:
                    reply = await self._extract_single_comment(el, post_id, parent_comment_id)
                    if reply and reply.comment_id not in seen_ids:
                        reply.depth = 1
                        replies.append(reply)
                        seen_ids.add(reply.comment_id)
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Reply extraction error: {e}")
        return replies

    async def _get_comment_id(self, el: ElementHandle) -> Optional[str]:
        """Try to find a stable comment ID from data attributes or anchor links"""
        try:
            anchor = await el.query_selector('a[href*="comment_id"]')
            if anchor:
                href = await anchor.get_attribute("href")
                m = re.search(r"comment_id[=:](\d+)", href or "")
                if m:
                    return m.group(1)

            # Try data-commentid attribute
            cid = await el.get_attribute("data-commentid")
            if cid:
                return cid

            # Hash bao gồm author + text + aria-label để tránh collision giữa comments "." "." "."
            aria = await el.get_attribute("aria-label") or ""
            author_el = await el.query_selector('a[role="link"]')
            author_href = (await author_el.get_attribute("href") or "") if author_el else ""
            text_el = await el.query_selector("div[dir='auto']")
            text = (await text_el.inner_text()) if text_el else ""
            key = f"{aria}|{author_href}|{text}"
            return f"cmt_{hash(key) & 0xFFFFFFFF:x}"
        except Exception:
            pass
        return None

    async def _extract_comment_timestamp(self, el: ElementHandle) -> Optional[str]:
        try:
            ts = await el.query_selector("abbr[data-utime]")
            if ts:
                utime = await ts.get_attribute("data-utime")
                if utime:
                    from datetime import datetime, timezone
                    return datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
                return await ts.get_attribute("title")
            # Try aria-label on time link
            time_link = await el.query_selector('a[aria-label]')
            if time_link:
                label = await time_link.get_attribute("aria-label")
                return label
        except Exception:
            pass
        return None

    async def _extract_comment_likes(self, el: ElementHandle) -> int:
        try:
            # aria-label format: "58 cảm xúc; xem ai đã bày tỏ cảm xúc về bình luận này"
            for sel in [
                '[aria-label*="cảm xúc"]',
                '[aria-label*="reaction"]',
                '[aria-label*="reactions"]',
            ]:
                like_el = await el.query_selector(sel)
                if like_el:
                    label = await like_el.get_attribute("aria-label") or ""
                    m = re.search(r"^([\d,\.]+[kKmM]?)\s", label)
                    if m:
                        return parse_count(m.group(1))
        except Exception:
            pass
        return 0

    async def _extract_comment_images(self, el: ElementHandle) -> List[str]:
        urls = []
        try:
            imgs = await el.query_selector_all('img[src*="fbcdn.net"]')
            for img in imgs:
                src = await img.get_attribute("src")
                if not src:
                    continue
                # Loại emoji icons (static assets) và reaction images
                if "emoji" in src or "/rsrc.php/" in src or "static.xx.fbcdn" in src:
                    continue
                # Chỉ lấy ảnh user-upload (scontent CDN) hoặc external preview
                if "scontent" in src or "external" in src:
                    urls.append(src)
        except Exception:
            pass
        return urls

