"""
Post data extractor from Playwright page.
Handles both www.facebook.com and mbasic.facebook.com.
"""
import asyncio
import re
import unicodedata
from typing import Optional, Dict, Any, List
from playwright.async_api import Page
from loguru import logger

from ..graph.schema import PostNode
from ..utils.helpers import (
    extract_post_id, extract_user_id, extract_hashtags,
    extract_mentions, extract_emojis, extract_external_links,
    clean_text, parse_count, normalize_fb_url
)


class PostExtractor:
    """Extracts structured PostNode data from a Facebook post page or feed item"""

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config

    async def extract_from_url(self, page: Page, url: str) -> Optional[PostNode]:
        """Navigate to post URL and extract full post data"""
        try:
            is_photo = "/photo/" in url or "fbid=" in url
            # networkidle đảm bảo chỉ có post chính load, related posts chưa lazy-load
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            await self._dismiss_dialogs(page)
            if is_photo:
                return await self._extract_photo_page(page, url)
            return await self._extract_post_data(page, url)
        except Exception as e:
            logger.error(f"Failed to extract post from {url}: {e}")
            return None

    async def _extract_photo_page(self, page: Page, url: str) -> Optional[PostNode]:
        """Extract data from facebook.com/photo/?fbid=... viewer page"""
        post_id = extract_post_id(url) or f"unknown_{hash(url)}"

        # Wait for photo viewer content
        for sel in [
            '[data-pagelet="MediaViewerPhoto"]',
            '[role="main"]',
            'img[data-visualcompletion="media-vc-image"]',
        ]:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                break
            except Exception:
                continue

        await asyncio.sleep(1)

        right_panel = await page.query_selector('[role="complementary"]')
        caption_root = right_panel or page

        # Lấy author name TRƯỚC khi extract text, để dùng làm filter
        _page_author_name = ""
        if right_panel:
            try:
                for _sel in ['h2 a', 'h2', 'strong a']:
                    _a = await right_panel.query_selector(_sel)
                    if _a:
                        _t = (await _a.inner_text()).replace('﻿', '').strip()
                        if _t:
                            _page_author_name = _t
                            break
            except Exception:
                pass

        # Caption text: data-ad-* trước, fallback dir=auto (trước comments)
        raw_text = ""

        # Ưu tiên data-ad-* selectors — nhưng skip nếu text chỉ là tên page
        for sel in [
            'div[data-ad-rendering-role="story_message"]',
            'div[data-ad-comet-preview="message"]',
            'div[data-ad-preview="message"]',
        ]:
            try:
                el = await caption_root.query_selector(sel)
                if el:
                    t = (await el.inner_text()).strip()
                    if not t or len(t) <= 3:
                        continue
                    # Skip nếu text là tên page (có thể kèm badge xác minh). Strip BOM trước.
                    _t_norm = t.replace('﻿', '').replace('​', '')
                    if _page_author_name and _t_norm.startswith(_page_author_name):
                        continue
                    raw_text = t
                    break
            except Exception:
                continue

        # Fallback: dir=auto trong right panel, KHÔNG trong [role="article"] (comments).
        # Filter dùng innerText, nhưng return getTextWithEmoji() để capture emoji đúng.
        if not raw_text and right_panel:
            raw_text = await right_panel.evaluate("""(panel, authorName) => {
                function getTextWithEmoji(el) {
                    let r = '';
                    for (const n of el.childNodes) {
                        if (n.nodeType === Node.TEXT_NODE) r += n.textContent;
                        else if (n.nodeType === Node.ELEMENT_NODE) {
                            if (n.tagName === 'IMG') r += n.getAttribute('alt') || '';
                            else r += getTextWithEmoji(n);
                        }
                    }
                    return r;
                }

                const UI_NOISE = new Set(['đóng','close','trang chủ','notification',
                    'hãy là người đầu tiên bình luận.',
                    'be the first to comment.']);

                const divs = panel.querySelectorAll('[dir="auto"]');
                for (const d of divs) {
                    if (d.closest('[role="article"]') || d.closest('a') ||
                        d.closest('h1') || d.closest('h2') || d.closest('h3') ||
                        d.closest('[role="navigation"]') || d.closest('[role="button"]')) continue;

                    const t = d.innerText.trim();
                    if (!t || t.length < 5 || UI_NOISE.has(t.toLowerCase())) continue;
                    // Skip số thuần (pagination "6/247", reaction counts, ...)
                    if (/^[\\d\\s/.,-]+$/.test(t)) continue;
                    // Skip tên page/author (+ badge xác minh). Normalize BOM/ZWS trước khi so sánh.
                    const normT = t.replace(/[﻿​]/g, '');
                    const normAuthor = (authorName || '').replace(/[﻿​]/g, '');
                    if (normAuthor && normT.startsWith(normAuthor)) continue;
                    // Skip 1-2 từ ngắn có dấu chấm (tên miền)
                    const words = t.split(/\\s+/).filter(w => w.length > 0);
                    if (words.length <= 2 && t.includes('.') && t.length < 30) continue;
                    // Skip FB obfuscated single-char lines
                    const lines = t.split('\\n').filter(l => l.trim().length > 0);
                    const singles = lines.filter(l => l.trim().length <= 1).length;
                    if (lines.length > 4 && singles / lines.length > 0.5) continue;

                    return getTextWithEmoji(d).trim();
                }
                return '';
            }""", _page_author_name)

        cleaned = clean_text(raw_text)
        author_id, author_name = await self._extract_page_author(page)
        timestamp = await self._extract_page_timestamp(page)
        image_urls = await self._extract_photo_image(page, url)
        timestamp = await self._extract_photo_timestamp(page) or timestamp
        reactions = await self._extract_page_reactions(page)
        if reactions["comment_count"] == 0:
            reactions["comment_count"] = await self._get_comment_count_from_html(page)
        if reactions["share_count"] == 0:
            reactions["share_count"] = await self._get_share_count_from_html(page)
        location = await self._extract_page_location(page)
        tagged = await self._extract_tagged_users(page)

        return PostNode(
            post_id=post_id,
            post_url=normalize_fb_url(url),
            raw_text=raw_text,
            cleaned_text=cleaned,
            hashtags=extract_hashtags(raw_text),
            mentions=extract_mentions(raw_text),
            emojis=extract_emojis(raw_text),
            external_links=extract_external_links(raw_text),
            author_id=author_id,
            author_name=author_name,
            timestamp=timestamp,
            image_urls=image_urls,
            location=location,
            tagged_users=tagged,
            source_page=url,
            post_type="photo",
            **reactions,
        )

    async def _extract_photo_timestamp(self, page: Page) -> Optional[str]:
        """
        Photo viewer không có abbr[data-utime]. Timestamp nằm trong aria-label
        của comment author links: 'Bình luận dưới tên X vào Y tuần trước' hoặc
        trong link timestamp của bài viết.
        """
        try:
            # Thử link timestamp trực tiếp của post
            ts_el = await page.query_selector(
                '[aria-label*="tuần trước"], [aria-label*="tháng trước"], '
                '[aria-label*="giờ trước"], [aria-label*="phút trước"], '
                '[aria-label*="ngày trước"], [aria-label*="giây trước"], '
                '[aria-label*=" week"], [aria-label*=" hour"], [aria-label*=" day"], '
                '[aria-label*=" minute"]'
            )
            if ts_el:
                return await ts_el.get_attribute("aria-label")

            # Fallback: lấy từ abbr nếu có
            abbr = await page.query_selector("abbr[data-utime]")
            if abbr:
                utime = await abbr.get_attribute("data-utime")
                if utime:
                    from datetime import datetime, timezone
                    return datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
        except Exception:
            pass
        return None

    async def _extract_photo_image(self, page: Page, url: str) -> list:
        """
        Lấy ảnh CHÍNH của photo viewer — nằm ở LEFT panel, KHÔNG phải right panel (comments).
        Right panel = [role="complementary"] chứa comments và stickers.
        """
        urls = await page.evaluate("""() => {
            const rightPanel = document.querySelector('[role="complementary"]');

            // Main photo: img KHÔNG trong right panel
            const candidates = [...document.querySelectorAll(
                'img[data-visualcompletion="media-vc-image"], img[src*="scontent"][src*="fbcdn"]'
            )].filter(img => {
                if (!img.src) return false;
                if (img.src.includes('emoji') || img.src.includes('rsrc.php')) return false;
                if (rightPanel && rightPanel.contains(img)) return false;  // exclude right panel
                return true;
            }).map(img => img.src);

            return [...new Set(candidates)];
        }""")
        return urls

    async def extract_from_element(self, page: Page, element, feed_url: str) -> Optional[PostNode]:
        """Extract post data from a feed item element"""
        try:
            # Get post link
            post_url = await self._get_post_link(element)
            if not post_url:
                post_url = feed_url

            post_id = extract_post_id(post_url) or f"unknown_{hash(post_url)}"

            # Extract text content
            raw_text = await self._extract_text(element)
            cleaned = clean_text(raw_text)

            # Author
            author_id, author_name = await self._extract_author(element)

            # Timestamp
            timestamp = await self._extract_timestamp(element)

            # Media
            image_urls = await self._extract_images(element)
            video_urls = await self._extract_videos(element)

            # Engagement (may need to navigate to post for full counts)
            reactions = await self._extract_reactions_from_element(element)

            post = PostNode(
                post_id=post_id,
                post_url=normalize_fb_url(post_url),
                raw_text=raw_text,
                cleaned_text=cleaned,
                hashtags=extract_hashtags(raw_text),
                mentions=extract_mentions(raw_text),
                emojis=extract_emojis(raw_text),
                external_links=extract_external_links(raw_text),
                author_id=author_id,
                author_name=author_name,
                timestamp=timestamp,
                image_urls=image_urls,
                video_urls=video_urls,
                **reactions,
            )
            return post

        except Exception as e:
            logger.warning(f"Failed to extract post from element: {e}")
            return None

    async def _find_post_container(self, page: Page):
        """
        Tìm container chứa post chính trên permalink page.

        Strategy (từ research kevinzg/granary/mbasic):
        1. mbasic: #m_story_permalink_view — clean, không có related posts
        2. og:url → story_fbid → tìm article chứa link với numeric ID đó
        3. Pagelet selector fallback
        4. First article với data-ad-* content (least reliable)
        """
        # 1. mbasic container (nếu đang dùng mbasic)
        mbasic = await page.query_selector('#m_story_permalink_view, #MPhotoContent')
        if mbasic:
            return mbasic

        # 2. og:url → story_fbid → tìm article khớp
        # og:url luôn có dạng ...story_fbid=NUMERIC_ID&id=PAGE_ID
        story_fbid = await page.evaluate("""() => {
            const meta = document.querySelector('meta[property="og:url"]');
            if (!meta) return null;
            const url = meta.content || '';
            // Thử story_fbid param
            const m = url.match(/story_fbid=([0-9]+)/);
            if (m) return m[1];
            // Thử /posts/NUMERIC_ID
            const m2 = url.match(/\\/posts\\/([0-9]+)/);
            if (m2) return m2[1];
            return null;
        }""")

        if story_fbid:
            # Tìm article có link chứa story_fbid (timestamp link hoặc permalink)
            articles = await page.query_selector_all('[role="article"]')
            for article in articles:
                found = await article.evaluate(
                    f"(el, id) => !!el.querySelector('a[href*=\"' + id + '\"]')",
                    story_fbid
                )
                if found:
                    logger.debug(f"Found target article via story_fbid={story_fbid}")
                    return article

        # 3. Pagelet selector
        for sel in [
            '[data-pagelet="PermalinkPostFeed"]',
            '[data-pagelet*="Permalink"]',
            '[data-pagelet*="permalink"]',
        ]:
            el = await page.query_selector(sel)
            if el:
                return el

        # 4. First article với data-ad-* text (fallback, kém tin cậy)
        for article in await page.query_selector_all('[role="article"]'):
            for text_sel in [
                'div[data-ad-rendering-role="story_message"]',
                'div[data-ad-comet-preview="message"]',
                'div[data-ad-preview="message"]',
            ]:
                el = await article.query_selector(text_sel)
                if el and len((await el.inner_text()).strip()) > 5:
                    return article

        return None

    async def _get_post_text_element(self, page: Page):
        """
        Tìm đúng text element của post.
        Strategy:
        1. Title-based matching (NFC + whitespace + emoji normalize) — poll 6s
        2. og:description fallback — reliable meta tag, specific to current post
        Không dùng blind fallback (trả nhầm content từ related posts).
        """
        TEXT_SELS = [
            'div[data-ad-rendering-role="story_message"]',
            'div[data-ad-comet-preview="message"]',
            'div[data-ad-preview="message"]',
        ]

        def norm(s):
            """NFC + collapse whitespace + strip emoji (bao gồm chars FB render thành <img>)"""
            s = re.sub(r'[\U00010000-\U0010FFFF]', '', s)
            s = re.sub(r'[☀-➿⭐⭕︀-️\U0001F000-\U0001F9FF]', '', s)
            # Thêm: strip ‼ (U+203C), ⁉ (U+2049) và variation selectors
            s = re.sub(r'[‼⁉︎️]', '', s)
            return ' '.join(unicodedata.normalize('NFC', s).split())

        # ── Strategy 1: page title matching ──────────────────────────────────
        # Chờ title SPA update từ generic "Facebook" → "PageName - excerpt | Facebook"
        excerpt_norm = ""
        try:
            for _ in range(10):  # tối đa 5s chờ title update
                page_title = await page.title()
                if ' - ' in page_title and '| Facebook' in page_title:
                    break
                await asyncio.sleep(0.5)
            title_excerpt = re.sub(r'^\(\d+\)\s*[^-]+-\s*', '', page_title)
            title_excerpt = re.sub(r'\s*\|.*$', '', title_excerpt).strip()
            if title_excerpt and len(title_excerpt) > 1 and title_excerpt != 'Facebook':
                excerpt_norm = norm(title_excerpt[:25])
        except Exception:
            pass

        if excerpt_norm:
            for _ in range(6):  # poll tối đa 3s (title đã load rồi nên nhanh hơn)
                for sel in TEXT_SELS:
                    for el in await page.query_selector_all(sel):
                        text = (await el.inner_text()).strip()
                        if excerpt_norm in norm(text):
                            logger.debug(f"Matched via title+data-ad: {repr(text[:50])}")
                            return el, text

                dir_els = await page.query_selector_all('div[dir="auto"]')
                for el in dir_els:
                    outside = await el.evaluate(
                        "e => !e.closest('[role=\"article\"]') && "
                        "!e.closest('a') && !e.closest('h1') && "
                        "!e.closest('h2') && !e.closest('[role=\"navigation\"]')"
                    )
                    if not outside:
                        continue
                    text = (await el.inner_text()).strip()
                    if text and excerpt_norm in norm(text):
                        logger.debug(f"Matched via title+dir=auto: {repr(text[:50])}")
                        return el, text

                await asyncio.sleep(0.5)

            logger.warning(f"Title match failed for excerpt={repr(excerpt_norm[:20])}, trying og:description")

        # ── Strategy 2: og:description — reliable, post-specific ─────────────
        try:
            og_text = await page.evaluate("""() => {
                const m = document.querySelector('meta[property="og:description"]');
                return m ? m.getAttribute('content') : '';
            }""")
            og_text = (og_text or "").strip()
            if og_text and len(og_text) > 3:
                og_norm = norm(og_text[:25])
                # Tìm element khớp với og:description để vẫn có thể click "Xem thêm"
                for sel in TEXT_SELS:
                    for el in await page.query_selector_all(sel):
                        text = (await el.inner_text()).strip()
                        if og_norm in norm(text):
                            logger.debug(f"Matched via og:description+data-ad: {repr(text[:50])}")
                            return el, text
                # Element không tìm được nhưng og:description text là đúng
                logger.debug(f"og:description text only (no element): {repr(og_text[:50])}")
                return None, og_text
        except Exception as e:
            logger.debug(f"og:description fallback error: {e}")

        # ── Strategy 3: foreground container (data-thumb parent) ──────────────
        # Personal/creator pages không có excerpt trong title và og:description empty
        # → tìm data-ad-* element trong foreground container trực tiếp
        try:
            fg_el = await page.evaluate_handle("""() => {
                const thumbs = [...document.querySelectorAll('[data-thumb]')];
                let best = null, bestH = 0;
                for (const t of thumbs) {
                    const h = parseFloat(t.style.height || '0');
                    if (h > bestH) { bestH = h; best = t; }
                }
                if (!best || bestH < 200) return null;
                const container = best.parentElement;
                // Tìm data-ad-* element trong container
                const sels = [
                    'div[data-ad-rendering-role="story_message"]',
                    'div[data-ad-comet-preview="message"]',
                    'div[data-ad-preview="message"]',
                ];
                for (const sel of sels) {
                    const el = container.querySelector(sel);
                    if (el && el.innerText.trim().length > 2) return el;
                }
                return null;
            }""")
            fg_text_el = fg_el.as_element()
            if fg_text_el:
                text = (await fg_text_el.inner_text()).strip()
                if text and len(text) > 2:
                    logger.debug(f"Matched via foreground container: {repr(text[:50])}")
                    return fg_text_el, text
        except Exception as e:
            logger.debug(f"Foreground container fallback error: {e}")

        return None, ""

    async def _extract_post_data(self, page: Page, url: str) -> Optional[PostNode]:
        """Full extraction từ post permalink page, dùng title matching để tránh lấy nhầm related posts"""
        post_id = extract_post_id(url) or f"unknown_{hash(url)}"

        try:
            await page.wait_for_selector(
                'div[data-ad-rendering-role="story_message"], '
                'div[data-ad-comet-preview="message"], '
                'div[data-ad-preview="message"]',
                timeout=10000
            )
        except Exception:
            pass

        # Chờ thêm để page render đủ (cần hơn networkidle + 2s vì data-ad elements load chậm)
        await asyncio.sleep(2)

        # Tìm TEXT element đúng của post (match với page title)
        text_el, raw_text = await self._get_post_text_element(page)

        # Click "Xem thêm" nếu text bị truncate
        if text_el and raw_text.endswith(('Xem thêm', 'See more')):
            try:
                parent = await text_el.evaluate_handle("el => el.closest('[role]') || el.parentElement")
                btn_parent = parent.as_element() or page
                for sel in ['div[role="button"]:has-text("Xem thêm")', 'div[role="button"]:has-text("See more")']:
                    btn = await btn_parent.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.5)
                        _, raw_text = await self._get_post_text_element(page)
                        break
            except Exception:
                pass

        # Tìm container của post (để scope author, images)
        container = await self._find_post_container(page)
        target = container or page

        cleaned = clean_text(raw_text)
        author_id, author_name = await self._extract_author_from(target, page)
        timestamp = await self._extract_timestamp_from(target, page)
        # Scope images và reactions vào foreground container
        fg_container = await self._get_foreground_container(page)
        image_urls = await self._extract_images_from(fg_container or target)
        video_urls = await self._extract_videos_from(fg_container or target)
        # DOM scoped vào fg_container TRƯỚC — tránh lấy nhầm background feed portals
        reactions = await self._extract_page_reactions(page, scoped_root=fg_container)
        # HTML fill-in: bổ sung các type DOM còn 0, nhưng KHÔNG ghi đè giá trị DOM đã có
        html_reactions = await self._get_reactions_from_html(page, post_id)
        for k, v in html_reactions.items():
            if v > 0 and reactions.get(k, 0) == 0:
                reactions[k] = v
        if reactions["comment_count"] == 0:
            reactions["comment_count"] = await self._get_comment_count_from_html(page, post_id)
        if reactions["share_count"] == 0:
            reactions["share_count"] = await self._get_share_count_from_html(page)
        location = await self._extract_page_location(page)
        tagged = await self._extract_tagged_users_from(target)

        post = PostNode(
            post_id=post_id,
            post_url=normalize_fb_url(url),
            raw_text=raw_text,
            cleaned_text=cleaned,
            hashtags=extract_hashtags(raw_text),
            mentions=extract_mentions(raw_text),
            emojis=extract_emojis(raw_text),
            external_links=extract_external_links(raw_text),
            author_id=author_id,
            author_name=author_name,
            timestamp=timestamp,
            image_urls=image_urls,
            video_urls=video_urls,
            location=location,
            tagged_users=tagged,
            source_page=url,
            **reactions,
        )
        return post

    # ─── SCOPED EXTRACTION HELPERS ────────────────────────────────────────

    async def _extract_text_from(self, root) -> str:
        """Extract post text với emoji (img[alt]) từ root element"""
        for sel in [
            'div[data-ad-rendering-role="story_message"]',
            'div[data-ad-comet-preview="message"]',
            'div[data-ad-preview="message"]',
            '[data-testid="post_message"]',
            '[dir="auto"] > div > div > span',
            '.userContent',
        ]:
            try:
                el = await root.query_selector(sel)
                if el:
                    # Dùng getTextWithEmoji để capture emoji được render như <img alt="...">
                    text = await el.evaluate("""el => {
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
                        return g(el).trim();
                    }""")
                    if text and len(text) > 5:
                        return text
            except Exception:
                continue
        return ""

    async def _extract_author_from(self, root, fallback_page):
        for target in [root, fallback_page]:
            try:
                el = await target.query_selector(
                    'h2 a[href*="facebook.com"], h2 a[href^="/"], '
                    '[data-testid="actor-name"] a, strong a[href*="facebook.com"]'
                )
                if el:
                    name = (await el.inner_text()).strip()
                    href = await el.evaluate("e => e.href || e.getAttribute('href') || ''")
                    if href and href.startswith("/"):
                        href = "https://www.facebook.com" + href
                    uid = extract_user_id(href) or None
                    if name:
                        return uid, name
            except Exception:
                pass

        # Fallback: dùng page.url (Python) để extract slug, tìm page-level link trong DOM
        # Dùng cho page posts — tên page nằm trong link có href = /PageSlug (không có /posts/)
        try:
            from urllib.parse import urlparse as _urlparse
            current_url = fallback_page.url
            _parts = _urlparse(current_url).path.strip("/").split("/")
            if len(_parts) >= 2 and _parts[1] in ("posts", "permalink", "photos", "videos"):
                slug = _parts[0]
                link_els = await fallback_page.query_selector_all(f'a[href*="/{slug}"]')
                for link_el in link_els:
                    try:
                        href = await link_el.evaluate("e => e.href || ''")
                        if not href:
                            continue
                        _up = _urlparse(href)
                        _pp = [p for p in _up.path.split("/") if p]
                        if len(_pp) != 1 or _pp[0].lower() != slug.lower():
                            continue
                        name = await link_el.evaluate(
                            "e => (e.innerText || '').replace(/\\s+/g, ' ').trim()"
                        )
                        if not name or len(name) < 2 or name[0].isdigit():
                            continue
                        in_cmt = await link_el.evaluate(
                            "e => !!e.closest('[role=\"article\"]') || !!e.closest('[aria-label*=\"ụng\"]')"
                        )
                        if in_cmt:
                            continue
                        uid = extract_user_id(href) or None
                        return uid, name
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Author slug fallback error: {e}")

        # Fallback cuối: parse h2 text "Bài viết của {PageName}" / "Posts by {PageName}"
        try:
            result = await fallback_page.evaluate("""() => {
                const PREFIXES = ['Bài viết của ', 'Posts by ', 'Post by '];
                for (const h2 of document.querySelectorAll('h2')) {
                    const text = (h2.innerText || '').replace(/\\s+/g, ' ').trim();
                    for (const p of PREFIXES) {
                        if (text.startsWith(p)) {
                            const name = text.slice(p.length).trim();
                            if (name && name.length > 1) return name;
                        }
                    }
                }
                return null;
            }""")
            if result:
                return None, result
        except Exception:
            pass

        return None, None

    async def _extract_timestamp_from(self, root, fallback_page):
        for target in [root, fallback_page]:
            try:
                ts_el = await target.query_selector('abbr[data-utime], span abbr')
                if ts_el:
                    utime = await ts_el.get_attribute("data-utime")
                    if utime:
                        from datetime import datetime, timezone
                        return datetime.fromtimestamp(int(utime), tz=timezone.utc).isoformat()
                    return await ts_el.get_attribute("title")
            except Exception:
                pass
        return None

    # Paths của stickers, emojis, reaction icons — không phải ảnh bài post
    _EXCLUDE_IMG_PATHS = ("t39.1997-6", "t45.1600-4", "emoji", "/rsrc.php/", "static.xx.")

    async def _extract_images_from(self, root) -> list:
        urls = []
        try:
            imgs = await root.query_selector_all('img[src*="fbcdn.net"]:not([alt=""])')
            for img in imgs:
                src = await img.get_attribute("src")
                if not src or "fbcdn.net" not in src:
                    continue
                if any(p in src for p in self._EXCLUDE_IMG_PATHS):
                    continue
                # Exclude images inside comment articles (comment section trong cùng container)
                in_comment = await img.evaluate(
                    "el => !!el.closest('[aria-label*=\"Bình luận dưới tên\"]') || "
                    "!!el.closest('[aria-label*=\"Comment by\"]') || "
                    "!!el.closest('[role=\"article\"]')"
                )
                if in_comment:
                    continue
                if any(s in src for s in ["scontent", "_n.", "_o.", "1080", "720", "540"]):
                    urls.append(src)
        except Exception:
            pass
        try:
            imgs2 = await root.query_selector_all('img[data-src*="fbcdn.net"]')
            for img in imgs2:
                src = await img.get_attribute("data-src")
                if src and src not in urls:
                    urls.append(src)
        except Exception:
            pass
        return list(set(urls))

    async def _extract_videos_from(self, root) -> list:
        urls = []
        try:
            for v in await root.query_selector_all('video[src], video source[src]'):
                src = await v.get_attribute("src")
                if src:
                    urls.append(src)
        except Exception:
            pass
        return list(set(urls))

    # Slug của các path FB nội bộ — không phải user/page
    _FB_NAV_SLUGS = {
        'notifications', 'control_panel', 'friends', 'onthisday', 'saved',
        'reel', 'reels', 'ad_campaign', 'photo', 'photos', 'pages', 'groups',
        'events', 'marketplace', 'watch', 'gaming', 'fundraisers', 'memories',
        'bookmarks', 'weather', 'jobs', 'videos', 'live', 'stories', 'help',
        'login', 'settings', 'privacy', 'hashtag', 'search', 'home',
    }

    async def _extract_tagged_users_from(self, root) -> list:
        """Chỉ lấy @mention links trong phần text của post, lọc nav slugs."""
        tagged = []
        try:
            # Scope vào text elements của post (data-ad-* hoặc dir=auto trong article)
            for text_sel in [
                'div[data-ad-rendering-role="story_message"] a[href*="facebook.com"]',
                'div[data-ad-comet-preview="message"] a[href*="facebook.com"]',
                'div[data-ad-preview="message"] a[href*="facebook.com"]',
            ]:
                links = await root.query_selector_all(text_sel)
                for link in links[:30]:
                    href = await link.get_attribute("href") or ""
                    uid = extract_user_id(href)
                    if not uid:
                        continue
                    # Lọc FB nav paths và profile.php?id= dạng numeric
                    if uid in self._FB_NAV_SLUGS:
                        continue
                    if uid not in tagged:
                        tagged.append(uid)
                if tagged:
                    break
        except Exception:
            pass
        return tagged

    # ─── PAGE-LEVEL (fallback) ────────────────────────────────────────────

    async def _extract_page_text(self, page: Page) -> str:
        return await self._extract_text_from(page)

    async def _extract_text(self, element) -> str:
        try:
            # Try common post text containers
            for sel in [
                '[data-ad-preview="message"]',
                '[data-testid="post_message"]',
                '[dir="auto"]',
                'p',
                'span[dir]',
            ]:
                try:
                    el = await element.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        if text and len(text.strip()) > 2:
                            return text.strip()
                except Exception:
                    continue
            # Fallback: get all text from element
            return (await element.inner_text()).strip()
        except Exception:
            return ""

    # ─── AUTHOR EXTRACTION ───────────────────────────────────────────────

    async def _extract_page_author(self, page: Page):
        try:
            author_link = await page.query_selector(
                'h2 a[href*="facebook.com"], h2 a[href^="/"], '
                '[data-testid="actor-name"] a, '
                'strong a[href*="facebook.com"]'
            )
            if author_link:
                name = await author_link.inner_text()
                href = await author_link.evaluate("e => e.href || e.getAttribute('href') || ''")
                if href and href.startswith("/"):
                    href = "https://www.facebook.com" + href
                uid = extract_user_id(href) or None
                return uid, name.strip()
        except Exception:
            pass
        return None, None

    async def _extract_author(self, element):
        try:
            author_link = await element.query_selector(
                'h2 a, strong a, [data-testid="actor-name"] a'
            )
            if author_link:
                name = await author_link.inner_text()
                href = await author_link.get_attribute("href")
                uid = extract_user_id(href or "") or ""
                return uid, name.strip()
        except Exception:
            pass
        return None, None

    # ─── TIMESTAMP EXTRACTION ────────────────────────────────────────────

    async def _extract_page_timestamp(self, page: Page) -> Optional[str]:
        try:
            ts_el = await page.query_selector(
                'abbr[data-utime], '
                '[data-testid="story-subtitle"] abbr, '
                'a[aria-label] abbr, '
                'span[aria-label] abbr'
            )
            if ts_el:
                utime = await ts_el.get_attribute("data-utime")
                if utime:
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(int(utime), tz=timezone.utc)
                    return dt.isoformat()
                title = await ts_el.get_attribute("title")
                return title
        except Exception:
            pass
        return None

    async def _extract_timestamp(self, element) -> Optional[str]:
        try:
            ts_el = await element.query_selector(
                'abbr[data-utime], a[role="link"] abbr, span abbr'
            )
            if ts_el:
                utime = await ts_el.get_attribute("data-utime")
                if utime:
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(int(utime), tz=timezone.utc)
                    return dt.isoformat()
                return await ts_el.get_attribute("title")
        except Exception:
            pass
        return None

    # ─── MEDIA EXTRACTION ────────────────────────────────────────────────

    async def _extract_page_images(self, page: Page) -> List[str]:
        urls = []
        try:
            imgs = await page.query_selector_all(
                'img[src*="fbcdn.net"]:not([alt=""])'
            )
            for img in imgs:
                src = await img.get_attribute("src")
                if src and "fbcdn.net" in src and "emoji" not in src:
                    # Filter out profile/avatar images (small ones)
                    if any(size in src for size in ["_n.", "_o.", "1080", "720", "540"]):
                        urls.append(src)
        except Exception:
            pass

        # Also check data-src
        try:
            imgs = await page.query_selector_all('img[data-src*="fbcdn.net"]')
            for img in imgs:
                src = await img.get_attribute("data-src")
                if src and src not in urls:
                    urls.append(src)
        except Exception:
            pass

        return list(set(urls))

    async def _extract_images(self, element) -> List[str]:
        urls = []
        try:
            imgs = await element.query_selector_all('img[src*="fbcdn.net"]')
            for img in imgs:
                src = await img.get_attribute("src")
                if src and "fbcdn.net" in src and "emoji" not in src:
                    urls.append(src)
        except Exception:
            pass
        return list(set(urls))

    async def _extract_page_videos(self, page: Page) -> List[str]:
        urls = []
        try:
            videos = await page.query_selector_all('video[src], video source[src]')
            for v in videos:
                src = await v.get_attribute("src")
                if src:
                    urls.append(src)
        except Exception:
            pass
        return list(set(urls))

    async def _extract_videos(self, element) -> List[str]:
        urls = []
        try:
            videos = await element.query_selector_all('video[src], video source')
            for v in videos:
                src = await v.get_attribute("src")
                if src:
                    urls.append(src)
        except Exception:
            pass
        return list(set(urls))

    # ─── REACTIONS EXTRACTION ────────────────────────────────────────────

    async def _get_reactions_from_html(self, page: Page, post_id: str = "") -> Dict[str, int]:
        """
        Parse reaction counts từ FB embedded JSON (HTML source).
        Dùng story_fbid từ og:url để anchor vào đúng JSON block của post này.
        """
        reactions = {
            "like_count": 0, "love_count": 0, "haha_count": 0,
            "wow_count": 0, "sad_count": 0, "angry_count": 0, "care_count": 0,
        }
        REACTION_TYPE_MAP = {
            "LIKE": "like_count", "LOVE": "love_count", "HAHA": "haha_count",
            "WOW": "wow_count", "SAD": "sad_count", "ANGER": "angry_count",
            "CARE": "care_count", "PRIDE": "care_count",
        }
        try:
            html = await page.content()

            # Lấy story_fbid từ og:url để tìm đúng JSON block
            story_fbid = await page.evaluate("""() => {
                const m = document.querySelector('meta[property="og:url"]');
                if (!m) return '';
                const u = m.getAttribute('content') || '';
                const r = u.match(/story_fbid=([0-9]+)/);
                if (r) return r[1];
                const r2 = u.match(/\\/posts\\/([0-9]+)/);
                return r2 ? r2[1] : '';
            }""")

            anchor = story_fbid or post_id
            search_window = html

            if anchor:
                # Tìm vị trí anchor trong HTML (đây là ID của post hiện tại)
                idx = html.find(f'"{anchor}"')
                if idx < 0:
                    idx = html.find(anchor)
                if idx > 0:
                    # Search trong window xung quanh anchor (±5KB trước + 30KB sau)
                    search_window = html[max(0, idx - 5000):idx + 30000]

            # top_reactions: JSON object dạng {"reaction_type":"LIKE","count":N,...}
            # Dùng regex chặt hơn — match trong cùng 1 JSON object (không span qua objects)
            for m in re.finditer(
                r'\{[^{}]{0,200}"reaction_type"\s*:\s*"([A-Z]+)"[^{}]{0,200}"count"\s*:\s*(\d+)[^{}]{0,200}\}',
                search_window
            ):
                rtype, count = m.group(1), int(m.group(2))
                key = REACTION_TYPE_MAP.get(rtype)
                if key and reactions[key] == 0:
                    reactions[key] = count

            # Total reaction_count fallback
            if all(v == 0 for v in reactions.values()):
                m = re.search(r'"reaction_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)', search_window)
                if m:
                    reactions["like_count"] = int(m.group(1))

        except Exception as e:
            logger.debug(f"Reactions from HTML failed: {e}")
        return reactions

    async def _get_share_count_from_html(self, page: Page) -> int:
        """Parse share count từ JSON embedded trong HTML"""
        try:
            html = await page.content()
            # Pattern: "share_count":{"count":N} hoặc "reshare_count":N
            for pat in [
                r'"share_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)',
                r'"reshare_count"\s*:\s*(\d+)',
            ]:
                m = re.search(pat, html)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return 0

    async def _get_comment_count_from_html(self, page: Page, post_id: str = "") -> int:
        """
        Parse comment total_count từ FB embedded JSON.
        Dùng post_id để tìm đúng đoạn JSON của post này (tránh lấy nhầm related posts).
        """
        try:
            html = await page.content()
            pat = (
                r'"count"\s*:\s*\d+\s*,"page_size"\s*:\s*\d+\s*,'
                r'"total_count"\s*:\s*(\d+)\s*,"is_not_behind_the_fold"'
            )
            if post_id:
                # Tìm đoạn JSON có chứa post_id trước pattern
                idx = html.find(post_id)
                if idx >= 0:
                    # Tìm pattern trong window 50KB xung quanh post_id
                    window = html[max(0, idx-5000):idx+50000]
                    m = re.search(pat, window)
                    if m:
                        return int(m.group(1))
            # Fallback: first match
            m = re.search(pat, html)
            if m:
                return int(m.group(1))
        except Exception as e:
            logger.debug(f"Comment count from HTML failed: {e}")
        return 0

    async def _get_foreground_container(self, page: Page):
        """
        Trả về container của foreground post (data-thumb parent) để scope reactions.
        Tránh lấy nhầm reactions từ background news feed khi post mở đè lên feed.
        """
        handle = await page.evaluate_handle("""() => {
            const thumbs = [...document.querySelectorAll('[data-thumb]')];
            let best = null, bestH = 0;
            for (const t of thumbs) {
                const h = parseFloat(t.style.height || '0');
                if (h > bestH) { bestH = h; best = t; }
            }
            if (!best || bestH < 200) return null;
            return best.parentElement;
        }""")
        return handle.as_element()

    async def _extract_page_reactions(self, page: Page, scoped_root=None) -> Dict[str, int]:
        """Extract reactions. Nếu có scoped_root, tìm trong đó trước để tránh background feed."""
        reactions = {
            "like_count": 0, "love_count": 0, "haha_count": 0,
            "wow_count": 0, "sad_count": 0, "angry_count": 0,
            "care_count": 0, "comment_count": 0, "share_count": 0,
        }
        try:
            # Method 1: individual reaction aria-labels (vi) — format "Thích: 144 người"
            VN_REACTION_MAP = {
                "Thích":        "like_count",
                "Yêu thích":   "love_count",
                "Haha":         "haha_count",
                "Wow":          "wow_count",
                "Buồn":         "sad_count",
                "Phẫn nộ":     "angry_count",
                "Thương thương":"care_count",
            }
            # Nếu có scoped_root thì CHỈ tìm trong đó — không fallback toàn page
            # (tránh lấy nhầm reactions từ background feed portals)
            search_roots = [scoped_root] if scoped_root else [page]
            for vn_name, key in VN_REACTION_MAP.items():
                try:
                    for root in search_roots:
                        el = await root.query_selector(f'[aria-label*="{vn_name}:"]')
                        if el:
                            label = await el.get_attribute("aria-label") or ""
                            m = re.search(r"([\d,\.]+[kKmM]?)\s*người", label, re.IGNORECASE)
                            if m:
                                reactions[key] = parse_count(m.group(1))
                                break
                except Exception:
                    continue

            # Method 2: English reaction aria-labels — "Like: 144 people"
            EN_REACTION_MAP = {
                "Like": "like_count", "Love": "love_count",
                "Haha": "haha_count", "Wow": "wow_count",
                "Sad":  "sad_count",  "Angry": "angry_count",
                "Care": "care_count",
            }
            for en_name, key in EN_REACTION_MAP.items():
                if reactions[key] > 0:
                    continue
                try:
                    for root in search_roots:
                        el = await root.query_selector(f'[aria-label*="{en_name}:"]')
                        if el:
                            label = await el.get_attribute("aria-label") or ""
                            m = re.search(r"([\d,\.]+[kKmM]?)\s*people", label, re.IGNORECASE)
                            if m:
                                reactions[key] = parse_count(m.group(1))
                                break
                except Exception:
                    continue

            # Method 3: body text regex fallback (regular post pages)
            if all(v == 0 for v in reactions.values()):
                body_text = await page.evaluate("document.body.innerText") or ""
                for pattern, key in [
                    (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:lượt thích|Thích\b|Like[s]?\b)", "like_count"),
                    (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:bình luận\b|Comment[s]?\b)", "comment_count"),
                    (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:lượt chia sẻ|Chia sẻ\b|Share[s]?\b)", "share_count"),
                ]:
                    m = re.search(pattern, body_text, re.IGNORECASE)
                    if m:
                        val = parse_count(m.group(1).replace(" ", ""))
                        if val > 0:
                            reactions[key] = val

        except Exception as e:
            logger.debug(f"Reaction extraction error: {e}")

        return reactions

    async def _extract_reactions_from_element(self, element) -> Dict[str, int]:
        reactions = {
            "like_count": 0, "love_count": 0, "haha_count": 0,
            "wow_count": 0, "sad_count": 0, "angry_count": 0,
            "care_count": 0, "comment_count": 0, "share_count": 0,
        }
        try:
            text = await element.inner_text()

            count_patterns = [
                (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:lượt thích|Thích\b|like[s]?\b)", "like_count"),
                (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:bình luận\b|comment[s]?\b)", "comment_count"),
                (r"([\d][,\d]*\.?\d*\s*[kKmMtT]?)\s*(?:lượt chia sẻ|chia sẻ\b|share[s]?\b)", "share_count"),
            ]
            for pattern, key in count_patterns:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    val = parse_count(m.group(1).replace(" ", ""))
                    if val > 0:
                        reactions[key] = val

            # Try aria-label on action buttons inside the element
            for btn_sel, key in [
                ('[aria-label*="reaction"], [aria-label*="thích"]', "like_count"),
                ('[aria-label*="comment"], [aria-label*="bình luận"]', "comment_count"),
                ('[aria-label*="share"], [aria-label*="chia sẻ"]', "share_count"),
            ]:
                if reactions[key] > 0:
                    continue
                try:
                    el = await element.query_selector(btn_sel)
                    if el:
                        label = await el.get_attribute("aria-label") or ""
                        m = re.search(r"[\d,\.]+\s*[kKmMtT]?", label)
                        if m:
                            val = parse_count(m.group(0).replace(" ", ""))
                            if val > 0:
                                reactions[key] = val
                except Exception:
                    continue

        except Exception:
            pass
        return reactions

    # ─── MISC ─────────────────────────────────────────────────────────────

    async def _get_post_link(self, element) -> Optional[str]:
        try:
            # Look for timestamp link (most reliable post URL)
            link_el = await element.query_selector(
                'a[href*="/posts/"], '
                'a[href*="story_fbid"], '
                'a[href*="/permalink/"], '
                'a[href*="/reel/"], '
                'abbr ~ a'
            )
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        return "https://www.facebook.com" + href
                    return href
        except Exception:
            pass
        return None

    async def _extract_page_location(self, page: Page) -> Optional[str]:
        try:
            loc_el = await page.query_selector(
                '[data-testid="event-permalink-location"], '
                'a[href*="map"], '
                '[class*="location"]'
            )
            if loc_el:
                return (await loc_el.inner_text()).strip()
        except Exception:
            pass
        return None

    async def _extract_tagged_users(self, page: Page) -> List[str]:
        return await self._extract_tagged_users_from(page)

    async def _dismiss_dialogs(self, page: Page):
        """Dismiss login banner / cookie consent — KHÔNG click X của post viewer.

        Nút X post viewer có ancestors: div > div > div > div > div (generic, không có banner/dialog).
        Nút đóng banner login có ancestors: div[banner] > ... — chỉ target cái này.
        """
        dismiss_selectors = [
            # Banner login / cookie consent (có attribute "banner" trong ancestor)
            'div[banner] [aria-label="Đóng"]',
            'div[banner] [aria-label="Close"]',
            # Cookie policy button (có data-testid cụ thể)
            'div[data-testid="cookie-policy-manage-dialog-accept-button"]',
        ]
        for sel in dismiss_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                continue
