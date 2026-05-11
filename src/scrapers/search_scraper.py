"""
Facebook Search scraper - find public posts by keyword/hashtag.
"""
import asyncio
from typing import AsyncIterator, Dict, Any
from urllib.parse import quote
from playwright.async_api import BrowserContext
from loguru import logger

from .page_scraper import PageScraper
from ..graph.schema import GraphSample
from ..utils.helpers import human_delay


class SearchScraper(PageScraper):
    """Scrape public posts via Facebook search"""

    SEARCH_URL = "https://www.facebook.com/search/posts?q={query}&filters={filters}"

    async def scrape_search(
        self, query: str, max_posts: int = 100
    ) -> AsyncIterator[GraphSample]:
        """Search for public posts by keyword"""
        page = await self.get_page()
        encoded_query = quote(query)
        url = f"https://www.facebook.com/search/posts?q={encoded_query}"

        logger.info(f"Starting search scrape for: '{query}'")

        success = await self.navigate_safely(page, url)
        if not success:
            logger.error(f"Search navigation failed for: {query}")
            return

        await self.dismiss_popups(page)
        await asyncio.sleep(3)

        scraped = 0
        seen_post_ids = set()

        while scraped < max_posts:
            post_elements = await page.query_selector_all('[role="article"]')

            new_this_round = 0
            for el in post_elements:
                if scraped >= max_posts:
                    break

                try:
                    post = await self.post_extractor.extract_from_element(page, el, url)
                    if not post or not post.post_id:
                        continue
                    if post.post_id in seen_post_ids:
                        continue

                    seen_post_ids.add(post.post_id)
                    post.source_page = f"search:{query}"

                    if post.post_url and post.post_url != url:
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

                    logger.info(f"Search result {scraped}: {post.post_id} | '{query}'")
                    yield sample

                    await human_delay(1.5, 3.5)

                except Exception as e:
                    logger.warning(f"Search post error: {e}")
                    continue

            if new_this_round == 0:
                break

            await self.scroll_and_load(page, target_items=scraped + 10)

    async def scrape_hashtag(
        self, hashtag: str, max_posts: int = 100
    ) -> AsyncIterator[GraphSample]:
        """Scrape posts with a specific hashtag"""
        # Remove # if present
        tag = hashtag.lstrip("#")
        url = f"https://www.facebook.com/hashtag/{tag}"

        page = await self.get_page()
        success = await self.navigate_safely(page, url)
        if not success:
            logger.error(f"Hashtag navigation failed: #{tag}")
            return

        logger.info(f"Scraping hashtag: #{tag}")
        await self.dismiss_popups(page)
        await asyncio.sleep(3)

        scraped = 0
        seen_ids = set()

        while scraped < max_posts:
            post_elements = await page.query_selector_all('[role="article"]')

            new_this_round = 0
            for el in post_elements:
                if scraped >= max_posts:
                    break
                try:
                    post = await self.post_extractor.extract_from_element(page, el, url)
                    if not post or post.post_id in seen_ids:
                        continue

                    seen_ids.add(post.post_id)
                    post.source_page = f"hashtag:#{tag}"
                    if tag not in post.hashtags:
                        post.hashtags.append(tag)

                    post = await self.media_extractor.process_post_media(post)
                    comments, comment_edges = [], []
                    if self.scrape_comments and post.post_url:
                        comments, comment_edges = await self._get_post_comments(post)

                    sample = self._build_sample(post, None, comments, comment_edges)
                    scraped += 1
                    new_this_round += 1
                    logger.info(f"Hashtag #{tag} post {scraped}: {post.post_id}")
                    yield sample
                    await human_delay(1.5, 3.5)
                except Exception as e:
                    logger.warning(f"Hashtag post error: {e}")

            if new_this_round == 0:
                break
            await self.scroll_and_load(page, target_items=scraped + 10)
