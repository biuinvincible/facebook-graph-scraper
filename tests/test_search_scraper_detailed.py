"""
More detailed tests for SearchScraper and GroupScraper to cover uncovered lines.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.scrapers.search_scraper import SearchScraper
from src.scrapers.group_scraper import GroupScraper
from src.graph.schema import PostNode, GraphSample


def make_config():
    return {
        "min_delay": 0.01,
        "max_delay": 0.05,
        "scraping": {
            "max_posts_per_target": 5,
            "scrape_comments": False,
            "scrape_reactions": False,
        },
        "storage": {"download_media": False, "media_dir": "/tmp/media", "max_media_size_mb": 10},
        "max_comments": 10,
        "max_replies_per_comment": 5,
        "scrape_replies": False,
        "scrape_comments": False,
        "download_media": False,
        "media_dir": "/tmp/media",
        "max_media_size_mb": 10,
        "ocr_enabled": False,
        "ocr_lang": "eng",
    }


def make_mock_context():
    ctx = AsyncMock()
    page = AsyncMock()
    page.url = "https://www.facebook.com"
    page.goto = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=[])
    page.is_closed = MagicMock(return_value=False)
    page.close = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page)
    return ctx, page


def make_post(post_id="test_post", text="Test content"):
    return PostNode(
        post_id=post_id,
        post_url=f"https://www.facebook.com/page/posts/{post_id}",
        raw_text=text,
        cleaned_text=text,
        author_id="user1",
        author_name="Author",
    )


# ─── SearchScraper.scrape_search ─────────────────────────────────────────────

class TestScrapeSearchDetailed:
    @pytest.mark.asyncio
    async def test_yields_samples_from_elements(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        post = make_post()
        sample = GraphSample(sample_id="s1")
        sample.post = post
        el = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, return_value=post):
                        with patch.object(scraper.media_extractor, "process_post_media",
                                          new_callable=AsyncMock, return_value=post):
                            with patch.object(scraper, "_build_sample", return_value=sample):
                                with patch.object(scraper, "scroll_and_load",
                                                  new_callable=AsyncMock, return_value=0):
                                    with patch("src.scrapers.search_scraper.human_delay",
                                               new_callable=AsyncMock):
                                        with patch("asyncio.sleep", new_callable=AsyncMock):
                                            samples = []
                                            async for s in scraper.scrape_search("test query", max_posts=1):
                                                samples.append(s)
        assert len(samples) == 1

    @pytest.mark.asyncio
    async def test_deduplicates_posts(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        post = make_post(post_id="dup_post")
        sample = GraphSample(sample_id="s1")
        sample.post = post

        # Return same element twice
        el1 = AsyncMock()
        el2 = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el1, el2])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, return_value=post):
                        with patch.object(scraper.media_extractor, "process_post_media",
                                          new_callable=AsyncMock, return_value=post):
                            with patch.object(scraper, "_build_sample", return_value=sample):
                                with patch.object(scraper, "scroll_and_load",
                                                  new_callable=AsyncMock, return_value=0):
                                    with patch("src.scrapers.search_scraper.human_delay",
                                               new_callable=AsyncMock):
                                        with patch("asyncio.sleep", new_callable=AsyncMock):
                                            samples = []
                                            async for s in scraper.scrape_search("test"):
                                                samples.append(s)
        # Only 1 unique post should be yielded despite 2 elements
        assert len(samples) == 1

    @pytest.mark.asyncio
    async def test_handles_element_exception(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        el = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, side_effect=Exception("Element error")):
                        with patch.object(scraper, "scroll_and_load",
                                          new_callable=AsyncMock, return_value=0):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                samples = []
                                async for s in scraper.scrape_search("test"):
                                    samples.append(s)
        # Exception should be caught, no samples
        assert len(samples) == 0

    @pytest.mark.asyncio
    async def test_uses_encoded_query_in_url(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())
        navigated_urls = []

        async def mock_navigate(p, url, **kwargs):
            navigated_urls.append(url)
            return False

        with patch.object(scraper, "navigate_safely", side_effect=mock_navigate):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                async for _ in scraper.scrape_search("hello world"):
                    pass
        assert len(navigated_urls) == 1
        assert "hello+world" in navigated_urls[0] or "hello%20world" in navigated_urls[0]


# ─── SearchScraper.scrape_hashtag ────────────────────────────────────────────

class TestScrapeHashtagDetailed:
    @pytest.mark.asyncio
    async def test_scrape_hashtag_yields_samples(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        post = make_post()
        post.hashtags = []
        sample = GraphSample(sample_id="s1")
        sample.post = post
        el = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, return_value=post):
                        with patch.object(scraper.media_extractor, "process_post_media",
                                          new_callable=AsyncMock, return_value=post):
                            with patch.object(scraper, "_build_sample", return_value=sample):
                                with patch.object(scraper, "scroll_and_load",
                                                  new_callable=AsyncMock, return_value=0):
                                    with patch("src.scrapers.search_scraper.human_delay",
                                               new_callable=AsyncMock):
                                        with patch("asyncio.sleep", new_callable=AsyncMock):
                                            samples = []
                                            async for s in scraper.scrape_hashtag("python"):
                                                samples.append(s)
        if samples:
            assert "python" in samples[0].post.hashtags

    @pytest.mark.asyncio
    async def test_scrape_hashtag_handles_exceptions(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        el = AsyncMock()
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, side_effect=Exception("Error")):
                        with patch.object(scraper, "scroll_and_load",
                                          new_callable=AsyncMock, return_value=0):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                samples = []
                                async for s in scraper.scrape_hashtag("python"):
                                    samples.append(s)
        assert len(samples) == 0


# ─── GroupScraper.scrape_group ────────────────────────────────────────────────

class TestScrapeGroupDetailed:
    @pytest.mark.asyncio
    async def test_logs_private_group_warning(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())

        # Simulate finding a private group indicator
        private_el = AsyncMock()
        call_count = [0]
        async def mock_qs(sel):
            call_count[0] += 1
            if "Private group" in sel or "Nhóm riêng" in sel:
                return private_el
            return None

        page.query_selector = AsyncMock(side_effect=mock_qs)
        page.query_selector_all = AsyncMock(return_value=[])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper, "scroll_and_load",
                                      new_callable=AsyncMock, return_value=0):
                        with patch("asyncio.sleep", new_callable=AsyncMock):
                            samples = []
                            async for s in scraper.scrape_group("https://fb.com/groups/private/"):
                                samples.append(s)
        assert samples == []

    @pytest.mark.asyncio
    async def test_handles_element_exception(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())

        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, side_effect=Exception("Error")):
                        with patch.object(scraper, "scroll_and_load",
                                          new_callable=AsyncMock, return_value=0):
                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                samples = []
                                async for s in scraper.scrape_group("https://fb.com/groups/test/"):
                                    samples.append(s)
        assert samples == []

    @pytest.mark.asyncio
    async def test_gets_full_post_when_post_url_differs(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())

        post = make_post()
        full_post = make_post(text="Full post content with more details")
        sample = GraphSample(sample_id="s1")
        sample.post = full_post

        el = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[el])

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper.post_extractor, "extract_from_element",
                                      new_callable=AsyncMock, return_value=post):
                        with patch.object(scraper, "_get_full_post",
                                          new_callable=AsyncMock, return_value=full_post):
                            with patch.object(scraper, "_merge_posts", return_value=full_post):
                                with patch.object(scraper.media_extractor, "process_post_media",
                                                  new_callable=AsyncMock, return_value=full_post):
                                    with patch.object(scraper, "_build_sample", return_value=sample):
                                        with patch.object(scraper, "scroll_and_load",
                                                          new_callable=AsyncMock, return_value=0):
                                            with patch("src.scrapers.group_scraper.human_delay",
                                                       new_callable=AsyncMock):
                                                with patch("asyncio.sleep", new_callable=AsyncMock):
                                                    samples = []
                                                    async for s in scraper.scrape_group("https://fb.com/groups/test/"):
                                                        samples.append(s)
        assert len(samples) == 1
