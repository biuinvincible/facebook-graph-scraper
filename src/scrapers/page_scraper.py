"""
Facebook Page / Public Profile post scraper.
Scrolls through posts, extracts full post data including comments.
"""
import asyncio
from typing import List, AsyncIterator, Dict, Any, Optional
from playwright.async_api import BrowserContext
from loguru import logger

from .base import BaseScraper
from ..graph.schema import PostNode, CommentNode, UserPostEdge, GraphSample, HashtagNode, PostHashtagEdge, CommentReplyEdge
from ..extractors.post_extractor import PostExtractor
from ..extractors.comment_extractor import CommentExtractor
from ..extractors.media_extractor import MediaExtractor
from ..extractors.user_extractor import UserExtractor
from ..graph.edge_builder import EdgeBuilder
from ..graph.schema import UserUserEdge
from ..utils.helpers import human_delay, extract_post_id, extract_mentions


class PageScraper(BaseScraper):
    """Scrapes all posts from a Facebook Page or public profile"""

    def __init__(self, context: BrowserContext, config: Dict[str, Any]):
        super().__init__(context, config)
        self.post_extractor = PostExtractor(config)
        self.comment_extractor = CommentExtractor(config)
        self.media_extractor = MediaExtractor(config.get("storage", {}))
        self.user_extractor = UserExtractor(config)
        self.edge_builder = EdgeBuilder()
        self.max_posts = config.get("scraping", {}).get("max_posts_per_target", 200)
        self.scrape_comments = config.get("scraping", {}).get("scrape_comments", True)
        self.scrape_reactions = config.get("scraping", {}).get("scrape_reactions", True)

    async def scrape_page(self, page_url: str) -> AsyncIterator[GraphSample]:
        """
        Async generator that yields GraphSample objects as posts are scraped.
        Strategy: collect post links from feed via JS, scroll để load thêm,
        process từng link riêng biệt — tránh dedup issue của extract_from_element.
        """
        from urllib.parse import urlparse
        feed_page = await self.get_page()
        logger.info(f"Starting page scrape: {page_url}")

        success = await self.navigate_safely(feed_page, page_url)
        if not success:
            logger.error(f"Failed to navigate to {page_url}")
            return

        await self.dismiss_popups(feed_page)
        await asyncio.sleep(5)  # chờ feed render lần đầu

        # Extract page slug để filter chỉ lấy posts của page đó
        _slug = urlparse(page_url).path.strip("/").split("/")[0]

        def _collect_links(all_links: list, seen: set) -> list:
            new = [l for l in all_links if l not in seen]
            for l in new:
                seen.add(l)
            return new

        JS_COLLECT = """
            (slug) => {
                const seen = new Set();
                const result = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const h = a.href;
                    if (!h || h.includes('/reel/') || h.includes('/videos/')) return;
                    if (slug) {
                        const low = h.toLowerCase();
                        if (!low.includes('/' + slug + '/') && !low.includes('/' + slug + '?')) return;
                    }
                    if ((h.includes('/posts/') || h.includes('/permalink/') || h.includes('story_fbid='))
                        && !h.includes('/groups/')) {
                        const clean = h.split('?')[0];
                        if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
                    }
                });
                return result;
            }
        """

        scraped = 0
        seen_urls: set = set()
        no_new_streak = 0
        MAX_NO_NEW = 8  # dừng sau 8 lần scroll không thấy link mới

        while scraped < self.max_posts:
            # Scroll để load thêm posts
            await feed_page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(2.5)

            links = await feed_page.evaluate(JS_COLLECT, _slug)
            new_links = _collect_links(links, seen_urls)
            logger.debug(f"Feed scroll: found {len(links)} links total, {len(new_links)} new")

            if not new_links:
                no_new_streak += 1
                if no_new_streak >= MAX_NO_NEW:
                    logger.info(f"No new post links after {MAX_NO_NEW} scrolls — stopping feed")
                    break
                continue
            else:
                no_new_streak = 0

            # Process từng link mới
            for url in new_links:
                if scraped >= self.max_posts:
                    break

                tab = await self.context.new_page()
                try:
                    # Extract post + comments trong cùng 1 tab
                    post = await self.post_extractor.extract_from_url(tab, url)
                    if not post or (not post.raw_text and not post.image_urls):
                        continue

                    post = await self.media_extractor.process_post_media(post)

                    comments, comment_edges = [], []
                    if self.scrape_comments:
                        comments, comment_edges = await self.comment_extractor.extract_all_comments(
                            tab, post.post_id
                        )
                        comments = [
                            await self.media_extractor.process_comment_media(c, post.post_id)
                            if c.image_urls else c
                            for c in comments
                        ]

                    from ..graph.schema import UserNode
                    author_node = UserNode(
                        user_id=post.author_id or "",
                        display_name=post.author_name or "",
                    ) if post.author_id else None

                    sample = self._build_sample(post, author_node, comments, comment_edges)
                    scraped += 1
                    logger.info(f"Scraped post {scraped}/{self.max_posts}: {post.post_id} | "
                                f"{len(comments)} comments | {len(post.image_urls)} images")
                    yield sample

                    await human_delay(
                        self.cfg.get("min_delay", 1.5),
                        self.cfg.get("max_delay", 4.0),
                    )

                except Exception as e:
                    logger.warning(f"Post scraping error ({url[:60]}): {e}")
                finally:
                    await tab.close()
                    await asyncio.sleep(1)

        logger.info(f"Page scrape complete: {scraped} posts from {page_url}")

    async def _get_full_post(self, post_url: str) -> Optional[PostNode]:
        """Open post in new tab for full data extraction"""
        try:
            tab = await self.context.new_page()
            post = await self.post_extractor.extract_from_url(tab, post_url)
            await tab.close()
            return post
        except Exception as e:
            logger.debug(f"Full post extraction failed: {e}")
            return None

    async def _get_post_comments(self, post: PostNode):
        """Open post page and extract all comments"""
        try:
            tab = await self.context.new_page()
            success = await self.navigate_safely(tab, post.post_url)
            if not success:
                await tab.close()
                return [], []

            await asyncio.sleep(2)
            comments, edges = await self.comment_extractor.extract_all_comments(tab, post.post_id)
            # Download ảnh comment — MediaExtractor.download flag tự quyết có tải không
            comments = [
                await self.media_extractor.process_comment_media(c, post.post_id)
                if c.image_urls else c
                for c in comments
            ]
            await tab.close()
            return comments, edges
        except Exception as e:
            logger.warning(f"Comment extraction failed for {post.post_id}: {e}")
            return [], []

    def _merge_posts(self, feed_post: PostNode, full_post: PostNode) -> PostNode:
        """Merge data from feed element and full post page"""
        # Full post page has better reaction counts and text
        if full_post.raw_text and len(full_post.raw_text) > len(feed_post.raw_text or ""):
            feed_post.raw_text = full_post.raw_text
            feed_post.cleaned_text = full_post.cleaned_text

        if full_post.like_count > feed_post.like_count:
            feed_post.like_count = full_post.like_count

        feed_post.love_count = max(feed_post.love_count, full_post.love_count)
        feed_post.haha_count = max(feed_post.haha_count, full_post.haha_count)
        feed_post.comment_count = max(feed_post.comment_count, full_post.comment_count)
        feed_post.share_count = max(feed_post.share_count, full_post.share_count)

        # Merge media
        all_images = list(set(feed_post.image_urls + full_post.image_urls))
        feed_post.image_urls = all_images
        all_videos = list(set(feed_post.video_urls + full_post.video_urls))
        feed_post.video_urls = all_videos

        if full_post.location and not feed_post.location:
            feed_post.location = full_post.location

        if full_post.tagged_users:
            feed_post.tagged_users = list(set(feed_post.tagged_users + full_post.tagged_users))

        return feed_post

    def _build_sample(self, post, author, comments, comment_edges) -> GraphSample:
        sample = GraphSample()
        sample.post = post
        sample.author = author
        sample.comments = comments
        sample.edges_user_comment = comment_edges

        # Build user-post edges
        if author:
            author_edge = UserPostEdge(
                user_id=author.user_id,
                post_id=post.post_id,
                interaction_type="author",
            )
            sample.edges_user_post = [author_edge]

        # Build commenter nodes + edges
        seen_users = set()
        seen_uu_edges = set()  # (src, tgt, type) để tránh duplicate UserUserEdge
        comment_author_map: dict = {}  # comment_id → author_id (for reply edges)
        for comment in comments:
            comment_author_map[comment.comment_id] = comment.author_id

        for comment in comments:
            if comment.author_id and comment.author_id not in seen_users:
                seen_users.add(comment.author_id)
                from ..graph.schema import UserNode
                sample.commenters.append(UserNode(
                    user_id=comment.author_id,
                    display_name=comment.author_name,
                ))

            if comment.author_id:
                # NOTE: Không có User→[comment]→Post trực tiếp nữa.
                # GNN học quan hệ này qua 2-hop: User→[author]→Comment→[reply_to]→Post
                # Giữ lại User→[author]→Post chỉ cho page/post author (interaction_type="author")

                # Reply edge: commenter → parent commenter (User → User)
                if comment.parent_id:
                    parent_author = comment_author_map.get(comment.parent_id)
                    if parent_author and parent_author != comment.author_id:
                        key = (comment.author_id, parent_author, "reply")
                        if key not in seen_uu_edges:
                            seen_uu_edges.add(key)
                            sample.edges_user_user.append(UserUserEdge(
                                source_user_id=comment.author_id,
                                target_user_id=parent_author,
                                relation_type="reply",
                                timestamp=comment.timestamp,
                            ))

                # Mention edges từ @mention links trong comment text
                for m in getattr(comment, "mentioned_users", []):
                    from ..utils.helpers import extract_user_id as _uid
                    target_id = _uid(m.get("href", "")) or m.get("name", "")
                    if target_id and target_id != comment.author_id:
                        key = (comment.author_id, target_id, "mention")
                        if key not in seen_uu_edges:
                            seen_uu_edges.add(key)
                            sample.edges_user_user.append(UserUserEdge(
                                source_user_id=comment.author_id,
                                target_user_id=target_id,
                                relation_type="mention",
                                timestamp=comment.timestamp,
                            ))

        # Mention edges from post text
        for mention_slug in extract_mentions(post.raw_text or ""):
            if post.author_id:
                key = (post.author_id, mention_slug, "mention")
                if key not in seen_uu_edges:
                    seen_uu_edges.add(key)
                    sample.edges_user_user.append(UserUserEdge(
                        source_user_id=post.author_id,
                        target_user_id=mention_slug,
                        relation_type="mention",
                    ))

        # ── Bidirectional reversed edges (mention/reply) ──────────────────────
        reversed_edges = []
        for e in sample.edges_user_user:
            if e.relation_type in ("reply", "mention"):
                key = (e.target_user_id, e.source_user_id, f"{e.relation_type}_rev")
                if key not in seen_uu_edges:
                    seen_uu_edges.add(key)
                    reversed_edges.append(UserUserEdge(
                        source_user_id=e.target_user_id,
                        target_user_id=e.source_user_id,
                        relation_type=f"{e.relation_type}_rev",
                        timestamp=e.timestamp,
                    ))
        sample.edges_user_user.extend(reversed_edges)

        # ── Comment→[reply_to]→ Post/Comment (directed conversation tree) ─────
        from ..graph.schema import CommentReplyEdge
        for comment in comments:
            if comment.parent_id:
                # reply to another comment
                sample.edges_comment_reply.append(CommentReplyEdge(
                    comment_id=comment.comment_id,
                    target_id=comment.parent_id,
                    target_type="comment",
                    direction="reply_to",
                    timestamp=comment.timestamp,
                ))
                sample.edges_comment_reply.append(CommentReplyEdge(
                    comment_id=comment.parent_id,
                    target_id=comment.comment_id,
                    target_type="comment",
                    direction="reply_to_rev",
                    timestamp=comment.timestamp,
                ))
            else:
                # top-level: comment → post
                sample.edges_comment_reply.append(CommentReplyEdge(
                    comment_id=comment.comment_id,
                    target_id=post.post_id,
                    target_type="post",
                    direction="reply_to",
                    timestamp=comment.timestamp,
                ))

        # Reactions → stored as Post node features (like_count, haha_count, etc.)
        # not as edges: per-user react data not collectable from Facebook public pages

        # ── (Removed) Text/Image nodes → now stored as node features ─────────
        # Text/Image được embed offline thành node features của Post/Comment
        # không tạo node riêng để tránh node explosion O(N)
        # See: step 4&5 - offline BLIP-2/DINOv2 embedding pipeline


        # ── Hashtag nodes + Post→Hashtag edges ───────────────────────────────
        from ..graph.schema import HashtagNode, PostHashtagEdge

        all_tags: set = set(post.hashtags or [])
        for c in comments:
            all_tags.update(c.hashtags or [])

        seen_tags: dict = {}  # tag → HashtagNode
        for tag in all_tags:
            if tag not in seen_tags:
                seen_tags[tag] = HashtagNode(
                    hashtag=tag, frequency=1, post_ids=[post.post_id]
                )
            else:
                seen_tags[tag].frequency += 1

        sample.hashtags = list(seen_tags.values())

        for tag in all_tags:
            # Bidirectional: Post→Hashtag và Hashtag→Post
            sample.edges_post_hashtag.append(PostHashtagEdge(
                post_id=post.post_id, hashtag=tag, direction="has_hashtag"
            ))
            sample.edges_post_hashtag.append(PostHashtagEdge(
                post_id=post.post_id, hashtag=tag, direction="in_post"
            ))

        return sample
