"""
Tests for src/scrapers/page_scraper.py, group_scraper.py, search_scraper.py.
Mock-based tests that avoid launching real browsers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.scrapers.page_scraper import PageScraper
from src.scrapers.group_scraper import GroupScraper
from src.scrapers.search_scraper import SearchScraper
from src.graph.schema import PostNode, GraphSample, UserNode, CommentNode


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_mock_context():
    ctx = AsyncMock()
    page = AsyncMock()
    page.url = "https://www.facebook.com/TestPage"
    page.goto = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=None)
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock(return_value=[])
    page.is_closed = MagicMock(return_value=False)
    page.close = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page)
    return ctx, page


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


def make_post(post_id="test_post_001", text="Test content"):
    return PostNode(
        post_id=post_id,
        post_url=f"https://www.facebook.com/page/posts/{post_id}",
        raw_text=text,
        cleaned_text=text,
        author_id="user1",
        author_name="Test Author",
    )


# ─── PageScraper._merge_posts ─────────────────────────────────────────────────

class TestMergePosts:
    def test_takes_longer_text(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post(text="Short")
        full = make_post(text="This is a much longer and more complete text")
        result = scraper._merge_posts(feed, full)
        assert result.raw_text == full.raw_text

    def test_keeps_feed_text_when_longer(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post(text="This is a very long text from the feed element")
        full = make_post(text="Short")
        result = scraper._merge_posts(feed, full)
        assert result.raw_text == feed.raw_text

    def test_merges_image_urls(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post()
        feed.image_urls = ["https://cdn1.jpg"]
        full = make_post()
        full.image_urls = ["https://cdn2.jpg"]
        full.raw_text = "Slightly longer text here"
        result = scraper._merge_posts(feed, full)
        assert "https://cdn1.jpg" in result.image_urls
        assert "https://cdn2.jpg" in result.image_urls

    def test_takes_max_reaction_counts(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post()
        feed.like_count = 10
        feed.comment_count = 5
        full = make_post()
        full.like_count = 50
        full.comment_count = 20
        full.raw_text = "Slightly longer"
        result = scraper._merge_posts(feed, full)
        assert result.like_count == 50
        assert result.comment_count == 20

    def test_uses_full_post_location(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post()
        feed.location = None
        full = make_post()
        full.location = "Hanoi, Vietnam"
        full.raw_text = "Slightly longer"
        result = scraper._merge_posts(feed, full)
        assert result.location == "Hanoi, Vietnam"

    def test_merges_tagged_users(self):
        ctx, _ = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        feed = make_post()
        feed.tagged_users = ["user_a"]
        full = make_post()
        full.tagged_users = ["user_b"]
        full.raw_text = "Slightly longer"
        result = scraper._merge_posts(feed, full)
        assert "user_a" in result.tagged_users
        assert "user_b" in result.tagged_users


# ─── PageScraper._build_sample ────────────────────────────────────────────────

class TestBuildSample:
    def _make_scraper(self):
        ctx, _ = make_mock_context()
        return PageScraper(ctx, make_config())

    def test_builds_sample_with_author(self):
        scraper = self._make_scraper()
        post = make_post()
        author = UserNode(user_id="user1", display_name="Author")
        sample = scraper._build_sample(post, author, [], [])
        assert sample.post is post
        assert sample.author is author
        assert len(sample.edges_user_post) == 1
        assert sample.edges_user_post[0].interaction_type == "author"

    def test_builds_sample_without_author(self):
        scraper = self._make_scraper()
        post = make_post()
        sample = scraper._build_sample(post, None, [], [])
        assert sample.author is None
        assert sample.edges_user_post == []

    def test_builds_comment_edges(self):
        scraper = self._make_scraper()
        post = make_post()
        comment = CommentNode(
            comment_id="cmt1", post_id=post.post_id,
            author_id="user2", author_name="Commenter",
            raw_text="Nice!", cleaned_text="Nice!",
            parent_id=None, depth=0,
        )
        from src.graph.schema import UserCommentEdge
        edge = UserCommentEdge(user_id="user2", comment_id="cmt1", relation_type="author")
        sample = scraper._build_sample(post, None, [comment], [edge])
        assert len(sample.comments) == 1
        assert sample.edges_user_comment == [edge]

    def test_builds_hashtag_nodes(self):
        scraper = self._make_scraper()
        post = make_post()
        post.hashtags = ["hashtag1", "hashtag2"]
        sample = scraper._build_sample(post, None, [], [])
        assert len(sample.hashtags) == 2
        assert any(h.hashtag == "hashtag1" for h in sample.hashtags)

    def test_builds_reply_edges(self):
        scraper = self._make_scraper()
        post = make_post()
        parent_comment = CommentNode(
            comment_id="cmt_parent", post_id=post.post_id,
            author_id="user2", author_name="Parent Author",
            raw_text="Parent comment", cleaned_text="Parent comment",
            parent_id=None, depth=0,
        )
        child_comment = CommentNode(
            comment_id="cmt_child", post_id=post.post_id,
            author_id="user3", author_name="Child Author",
            raw_text="Child reply", cleaned_text="Child reply",
            parent_id="cmt_parent", depth=1,
        )
        sample = scraper._build_sample(post, None, [parent_comment, child_comment], [])
        # Should have reply edges for child_comment
        reply_edges = [e for e in sample.edges_comment_reply if e.direction == "reply_to"]
        assert any(e.comment_id == "cmt_child" and e.target_id == "cmt_parent" for e in reply_edges)

    def test_builds_mention_edges_from_post(self):
        scraper = self._make_scraper()
        post = make_post()
        post.raw_text = "Hello @friend how are you"
        post.author_id = "author1"
        sample = scraper._build_sample(post, None, [], [])
        mention_edges = [e for e in sample.edges_user_user if e.relation_type == "mention"]
        assert len(mention_edges) > 0

    def test_builds_user_user_reply_edge(self):
        scraper = self._make_scraper()
        post = make_post()
        parent_comment = CommentNode(
            comment_id="cmt_p", post_id=post.post_id,
            author_id="user_A", author_name="A",
            raw_text="text", cleaned_text="text",
            parent_id=None, depth=0,
        )
        reply_comment = CommentNode(
            comment_id="cmt_r", post_id=post.post_id,
            author_id="user_B", author_name="B",
            raw_text="reply", cleaned_text="reply",
            parent_id="cmt_p", depth=1,
        )
        sample = scraper._build_sample(post, None, [parent_comment, reply_comment], [])
        user_user_reply = [e for e in sample.edges_user_user if e.relation_type == "reply"]
        assert len(user_user_reply) > 0
        assert user_user_reply[0].source_user_id == "user_B"
        assert user_user_reply[0].target_user_id == "user_A"

    def test_deduplicates_commenters(self):
        scraper = self._make_scraper()
        post = make_post()
        # Same user comments twice
        c1 = CommentNode(
            comment_id="cmt_1", post_id=post.post_id,
            author_id="dup_user", author_name="Dup", raw_text="t", cleaned_text="t",
        )
        c2 = CommentNode(
            comment_id="cmt_2", post_id=post.post_id,
            author_id="dup_user", author_name="Dup", raw_text="t2", cleaned_text="t2",
        )
        sample = scraper._build_sample(post, None, [c1, c2], [])
        dup_users = [u for u in sample.commenters if u.user_id == "dup_user"]
        assert len(dup_users) == 1


# ─── PageScraper._get_full_post ───────────────────────────────────────────────

class TestGetFullPost:
    @pytest.mark.asyncio
    async def test_returns_post_on_success(self):
        ctx, page = make_mock_context()
        new_tab = AsyncMock()
        new_tab.close = AsyncMock()
        ctx.new_page = AsyncMock(return_value=new_tab)
        scraper = PageScraper(ctx, make_config())

        post = make_post()
        with patch.object(scraper.post_extractor, "extract_from_url", new_callable=AsyncMock, return_value=post):
            result = await scraper._get_full_post("https://fb.com/posts/123")
        assert result == post
        new_tab.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        ctx, page = make_mock_context()
        ctx.new_page = AsyncMock(side_effect=Exception("Browser error"))
        scraper = PageScraper(ctx, make_config())
        result = await scraper._get_full_post("https://fb.com/posts/123")
        assert result is None


# ─── PageScraper._get_post_comments ───────────────────────────────────────────

class TestGetPostComments:
    @pytest.mark.asyncio
    async def test_returns_empty_when_navigation_fails(self):
        ctx, page = make_mock_context()
        new_tab = AsyncMock()
        new_tab.close = AsyncMock()
        ctx.new_page = AsyncMock(return_value=new_tab)
        scraper = PageScraper(ctx, make_config())

        post = make_post()
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=False):
            comments, edges = await scraper._get_post_comments(post)
        assert comments == []
        assert edges == []
        new_tab.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_comments_on_success(self):
        ctx, page = make_mock_context()
        new_tab = AsyncMock()
        new_tab.close = AsyncMock()
        ctx.new_page = AsyncMock(return_value=new_tab)
        scraper = PageScraper(ctx, make_config())

        post = make_post()
        comment = CommentNode(
            comment_id="cmt1", post_id=post.post_id,
            raw_text="test", cleaned_text="test",
        )
        from src.graph.schema import UserCommentEdge
        edge = UserCommentEdge(user_id="u1", comment_id="cmt1", relation_type="author")

        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper.comment_extractor, "extract_all_comments",
                              new_callable=AsyncMock, return_value=([comment], [edge])):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    comments, edges = await scraper._get_post_comments(post)
        assert comments == [comment]
        assert edges == [edge]

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        ctx, page = make_mock_context()
        ctx.new_page = AsyncMock(side_effect=Exception("Tab error"))
        scraper = PageScraper(ctx, make_config())
        post = make_post()
        comments, edges = await scraper._get_post_comments(post)
        assert comments == []
        assert edges == []


# ─── PageScraper.scrape_page (generator) ──────────────────────────────────────

class TestScrapePage:
    @pytest.mark.asyncio
    async def test_stops_when_navigation_fails(self):
        ctx, page = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=False):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                samples = []
                async for sample in scraper.scrape_page("https://fb.com/Page"):
                    samples.append(sample)
        assert samples == []

    @pytest.mark.asyncio
    async def test_stops_when_no_new_links(self):
        ctx, page = make_mock_context()
        scraper = PageScraper(ctx, make_config())
        # navigate_safely succeeds, but evaluate returns no links
        page.evaluate = AsyncMock(return_value=[])
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        samples = []
                        async for sample in scraper.scrape_page("https://fb.com/Page"):
                            samples.append(sample)
        assert samples == []


# ─── GroupScraper.scrape_group ────────────────────────────────────────────────

class TestScrapeGroup:
    @pytest.mark.asyncio
    async def test_stops_when_navigation_fails(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=False):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                samples = []
                async for sample in scraper.scrape_group("https://fb.com/groups/test"):
                    samples.append(sample)
        assert samples == []

    @pytest.mark.asyncio
    async def test_stops_when_no_new_posts(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())
        page.query_selector_all = AsyncMock(return_value=[])
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper, "scroll_and_load", new_callable=AsyncMock, return_value=0):
                        with patch("asyncio.sleep", new_callable=AsyncMock):
                            samples = []
                            async for sample in scraper.scrape_group("https://fb.com/groups/test"):
                                samples.append(sample)
        assert samples == []

    @pytest.mark.asyncio
    async def test_yields_samples_for_posts(self):
        ctx, page = make_mock_context()
        scraper = GroupScraper(ctx, make_config())
        post = make_post()
        sample = GraphSample(sample_id="sample1")
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
                                with patch.object(scraper, "scroll_and_load", new_callable=AsyncMock, return_value=0):
                                    with patch("src.scrapers.group_scraper.human_delay", new_callable=AsyncMock):
                                        with patch("asyncio.sleep", new_callable=AsyncMock):
                                            samples = []
                                            async for s in scraper.scrape_group("https://fb.com/groups/test/"):
                                                samples.append(s)
        assert len(samples) == 1


# ─── SearchScraper.scrape_search ──────────────────────────────────────────────

class TestScrapeSearch:
    @pytest.mark.asyncio
    async def test_stops_when_navigation_fails(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=False):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                samples = []
                async for sample in scraper.scrape_search("test query"):
                    samples.append(sample)
        assert samples == []

    @pytest.mark.asyncio
    async def test_stops_when_no_elements(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())
        page.query_selector_all = AsyncMock(return_value=[])
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=True):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                with patch.object(scraper, "dismiss_popups", new_callable=AsyncMock):
                    with patch.object(scraper, "scroll_and_load", new_callable=AsyncMock, return_value=0):
                        with patch("asyncio.sleep", new_callable=AsyncMock):
                            samples = []
                            async for sample in scraper.scrape_search("test query"):
                                samples.append(sample)
        assert samples == []


# ─── SearchScraper.scrape_hashtag ─────────────────────────────────────────────

class TestScrapeHashtag:
    @pytest.mark.asyncio
    async def test_strips_hash_from_hashtag(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())
        navigated_urls = []

        async def mock_navigate(p, url, **kwargs):
            navigated_urls.append(url)
            return False  # fail so we stop early

        with patch.object(scraper, "navigate_safely", side_effect=mock_navigate):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                async for _ in scraper.scrape_hashtag("#vietnam"):
                    pass
        assert len(navigated_urls) == 1
        assert "vietnam" in navigated_urls[0]
        assert "#" not in navigated_urls[0]

    @pytest.mark.asyncio
    async def test_stops_when_navigation_fails(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())
        with patch.object(scraper, "navigate_safely", new_callable=AsyncMock, return_value=False):
            with patch.object(scraper, "get_page", new_callable=AsyncMock, return_value=page):
                samples = []
                async for sample in scraper.scrape_hashtag("vietnam"):
                    samples.append(sample)
        assert samples == []

    @pytest.mark.asyncio
    async def test_adds_hashtag_to_post(self):
        ctx, page = make_mock_context()
        scraper = SearchScraper(ctx, make_config())

        post = make_post()
        post.hashtags = []  # no hashtag initially
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
                                with patch.object(scraper, "scroll_and_load", new_callable=AsyncMock, return_value=0):
                                    with patch("src.scrapers.search_scraper.human_delay", new_callable=AsyncMock):
                                        with patch("asyncio.sleep", new_callable=AsyncMock):
                                            samples = []
                                            async for s in scraper.scrape_hashtag("vietnam"):
                                                samples.append(s)
        # The hashtag should be added if not already present
        if samples:
            assert "vietnam" in samples[0].post.hashtags


# ─── UserExtractor ────────────────────────────────────────────────────────────

class TestUserExtractor:
    @pytest.mark.asyncio
    async def test_extract_from_name_returns_user_node(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        result = await ext.extract_from_name(None, "user123", "Test User")
        assert result.user_id == "user123"
        assert result.display_name == "Test User"
        assert "user123" in result.profile_url

    @pytest.mark.asyncio
    async def test_extract_from_url_returns_none_on_error(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.goto = AsyncMock(side_effect=Exception("Error"))
        result = await ext.extract_from_url(page, "https://fb.com/user123")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_display_name(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        el = AsyncMock()
        el.inner_text = AsyncMock(return_value="Test Page Name")
        page.query_selector = AsyncMock(return_value=el)
        result = await ext._get_display_name(page)
        assert result == "Test Page Name"

    @pytest.mark.asyncio
    async def test_extract_display_name_returns_none(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_display_name(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_is_verified_returns_false(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_is_verified(page)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_is_verified_returns_true(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        badge = AsyncMock()
        page.query_selector = AsyncMock(return_value=badge)
        result = await ext._get_is_verified(page)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_bio_returns_none(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_bio(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_follower_count_returns_none(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_follower_count(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_location_returns_none(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._get_location(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_is_page_returns_false(self):
        from src.extractors.user_extractor import UserExtractor
        ext = UserExtractor({})
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await ext._is_page(page)
        assert result is False
