"""
Facebook Group post scraper.
Groups require login. Scrapes posts from public groups.
"""
import asyncio
from typing import AsyncIterator, Dict, Any, Optional
from playwright.async_api import BrowserContext
from loguru import logger

from .page_scraper import PageScraper
from ..graph.schema import GraphSample, UserNode
from ..utils.helpers import human_delay


class GroupScraper(PageScraper):
    """Scrapes posts from Facebook Groups"""

    async def scrape_group(self, group_url: str) -> AsyncIterator[GraphSample]:
        """Scrape all posts from a Facebook group"""
        page = await self.get_page()
        logger.info(f"Starting group scrape: {group_url}")

        # Ensure we're on the group's posts tab
        if not group_url.endswith("/"):
            group_url += "/"

        success = await self.navigate_safely(page, group_url)
        if not success:
            logger.error(f"Cannot navigate to group: {group_url}")
            return

        await self.dismiss_popups(page)
        await asyncio.sleep(3)

        # Check if group is accessible
        closed_indicators = [
            'div:has-text("Private group")',
            'div:has-text("Nhóm riêng tư")',
        ]
        for indicator in closed_indicators:
            el = await page.query_selector(indicator)
            if el:
                logger.warning(f"Group {group_url} is private — limited access")
                break

        scraped = 0
        seen_post_ids = set()

        while scraped < self.max_posts:
            # Groups use different article selectors
            post_elements = await page.query_selector_all(
                'div[data-pagelet*="GroupFeed"] [role="article"], '
                '[role="feed"] [role="article"]'
            )

            new_this_round = 0
            for el in post_elements:
                if scraped >= self.max_posts:
                    break

                try:
                    post = await self.post_extractor.extract_from_element(page, el, group_url)
                    if not post or not post.post_id:
                        continue

                    if post.post_id in seen_post_ids:
                        continue

                    seen_post_ids.add(post.post_id)
                    post.source_page = group_url

                    # Get full post
                    if post.post_url and post.post_url != group_url:
                        full_post = await self._get_full_post(post.post_url)
                        if full_post:
                            post = self._merge_posts(post, full_post)

                    post = await self.media_extractor.process_post_media(post)

                    comments, comment_edges = [], []
                    if self.scrape_comments and post.post_url:
                        comments, comment_edges = await self._get_post_comments(post)

                    sample = self._build_sample(post, None, comments, comment_edges)
                    scraped += 1
                    new_this_round += 1

                    logger.info(f"Group post {scraped}: {post.post_id} | {len(comments)} comments")
                    yield sample

                    await human_delay(1.5, 3.5)

                except Exception as e:
                    logger.warning(f"Group post error: {e}")
                    continue

            if new_this_round == 0:
                break

            await self.scroll_and_load(page, target_items=scraped + 10)

        logger.info(f"Group scrape done: {scraped} posts from {group_url}")
