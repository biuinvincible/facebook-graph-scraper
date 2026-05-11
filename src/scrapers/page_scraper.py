"""
Facebook Page / Public Profile post scraper.
Scrolls through posts, extracts full post data including comments.
"""
import asyncio
from typing import List, AsyncIterator, Dict, Any, Optional
from playwright.async_api import BrowserContext
from loguru import logger

from .base import BaseScraper
from ..graph.schema import PostNode, CommentNode, UserPostEdge, GraphSample
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
        Usage: async for sample in scraper.scrape_page(url): ...
        """
        page = await self.get_page()
        logger.info(f"Starting page scrape: {page_url}")

        # Navigate to page
        success = await self.navigate_safely(page, page_url)
        if not success:
            logger.error(f"Failed to navigate to {page_url}")
            return

        await self.dismiss_popups(page)
        await asyncio.sleep(2)

        # Get page author info
        author = await self.user_extractor._extract(page, page_url)

        scraped = 0
        seen_post_ids = set()
        no_new_posts_count = 0

        while scraped < self.max_posts:
            # Find post elements in current viewport
            post_elements = await page.query_selector_all(
                '[role="article"][data-pagelet*="FeedUnit"], '
                '[role="article"]:not([aria-label*="Comment"])'
            )

            new_this_round = 0
            for el in post_elements:
                if scraped >= self.max_posts:
                    break

                try:
                    # Quick extraction from feed element
                    post = await self.post_extractor.extract_from_element(page, el, page_url)
                    if not post or not post.post_id:
                        continue

                    if post.post_id in seen_post_ids:
                        continue

                    seen_post_ids.add(post.post_id)

                    # Set author info from page context
                    if author and not post.author_id:
                        post.author_id = author.user_id
                        post.author_name = author.display_name

                    # Get full post data by navigating to individual post
                    if post.post_url and post.post_url != page_url:
                        full_post = await self._get_full_post(post.post_url)
                        if full_post:
                            # Merge data (full post has more detail)
                            post = self._merge_posts(post, full_post)

                    # Download media & OCR
                    post = await self.media_extractor.process_post_media(post)

                    # Scrape comments
                    comments = []
                    comment_edges = []
                    if self.scrape_comments and post.post_url:
                        comments, comment_edges = await self._get_post_comments(post)

                    # Build graph sample
                    sample = self._build_sample(post, author, comments, comment_edges)

                    scraped += 1
                    new_this_round += 1
                    logger.info(f"Scraped post {scraped}/{self.max_posts}: {post.post_id} | "
                                f"{len(comments)} comments | {len(post.image_urls)} images")

                    yield sample

                    await human_delay(
                        self.cfg.get("scraper", {}).get("min_delay", 1.5),
                        self.cfg.get("scraper", {}).get("max_delay", 4.0),
                    )

                except Exception as e:
                    logger.warning(f"Post scraping error: {e}")
                    continue

            if new_this_round == 0:
                no_new_posts_count += 1
                if no_new_posts_count >= 3:
                    logger.info("No new posts found after 3 scroll attempts — stopping")
                    break
            else:
                no_new_posts_count = 0

            # Scroll to load more posts
            await self.scroll_and_load(page, target_items=scraped + 10, pause=2.5)

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
                # User → Post (comment edge)
                sample.edges_user_post.append(UserPostEdge(
                    user_id=comment.author_id,
                    post_id=post.post_id,
                    interaction_type="comment",
                    timestamp=comment.timestamp,
                ))

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

        # Mention edges from post text → User → Post author mentions
        for mention_slug in extract_mentions(post.raw_text or ""):
            if post.author_id:
                sample.edges_user_user.append(UserUserEdge(
                    source_user_id=post.author_id,
                    target_user_id=mention_slug,
                    relation_type="mention",
                ))

        return sample
