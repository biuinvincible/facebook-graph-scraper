"""
Tests for src/crawler.py — FacebookCrawler
"""
import os
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import AsyncIterator

from src.crawler import FacebookCrawler, BanException
from src.utils.ban_detector import BanType
from src.graph.schema import PostNode, GraphSample, UserNode


# ─── Minimal config fixture ───────────────────────────────────────────────────

MINIMAL_CONFIG = {
    "scraper": {
        "min_delay": 0.1,
        "max_delay": 0.2,
        "proxy": {"enabled": False, "list_file": "proxies/list.txt"},
    },
    "storage": {
        "db_path": ":memory:",
        "json_dir": "/tmp/test_json",
        "download_media": False,
        "media_dir": "/tmp/media",
        "max_media_size_mb": 10,
    },
    "scraping": {
        "max_comments": 10,
        "max_replies_per_comment": 5,
        "scrape_replies": False,
        "scrape_comments": False,
        "scrape_reactions": False,
        "max_posts_per_target": 5,
    },
    "protection": {
        "sessions_dir": "/tmp/cookies",
        "checkpoint_file": "/tmp/checkpoint.json",
        "checkpoint_flush_every": 100,
    },
    "ocr": {"enabled": False, "lang": "eng"},
    "logging": {"file": "/tmp/logs/test_scraper.log", "level": "DEBUG", "rotation": "1 MB"},
}


@pytest.fixture
def crawler(tmp_path):
    """Create a FacebookCrawler with mocked config and tmp paths"""
    config = dict(MINIMAL_CONFIG)
    config["protection"] = {
        "sessions_dir": str(tmp_path / "cookies"),
        "checkpoint_file": str(tmp_path / "checkpoint.json"),
        "checkpoint_flush_every": 100,
    }
    config["storage"] = {
        "db_path": str(tmp_path / "test.db"),
        "json_dir": str(tmp_path / "json"),
        "download_media": False,
        "media_dir": str(tmp_path / "media"),
        "max_media_size_mb": 10,
    }
    config["logging"] = {
        "file": str(tmp_path / "logs" / "test.log"),
        "level": "DEBUG",
        "rotation": "1 MB",
    }
    (tmp_path / "cookies").mkdir(exist_ok=True)

    with patch("yaml.safe_load", return_value=config):
        with patch("builtins.open", MagicMock()):
            with patch("src.crawler.ProxyManager") as MockProxy:
                MockProxy.return_value = MagicMock(enabled=False)
                with patch("src.crawler.SessionManager") as MockSession:
                    mock_sm = MagicMock()
                    mock_sm.get_active_session.return_value = MagicMock(
                        session_id="s1",
                        cookies_file="cookies/session.json",
                        requests_today=0,
                    )
                    mock_sm.status_summary = {"total": 1, "active": 1}
                    MockSession.return_value = mock_sm
                    with patch("src.crawler.ScrapingCheckpoint") as MockCP:
                        mock_cp = MagicMock()
                        mock_cp.scraped_count = 0
                        mock_cp.stats = {"total_scraped": 0}
                        mock_cp.is_scraped = MagicMock(return_value=False)
                        MockCP.return_value = mock_cp
                        cr = FacebookCrawler.__new__(FacebookCrawler)
                        cr.config = config
                        cr.storage_cfg = config["storage"]
                        cr.scraping_cfg = config["scraping"]
                        cr.scraper_cfg = config["scraper"]
                        from src.storage.database import Database
                        from src.storage.json_storage import JsonStorage
                        from src.graph.edge_builder import EdgeBuilder
                        from src.utils.ban_detector import BanDetector
                        from src.utils.rate_limiter import AdaptiveRateLimiter
                        from src.utils.checkpoint import ScrapingCheckpoint
                        cr.db = MagicMock()
                        cr.db.__aenter__ = AsyncMock(return_value=cr.db)
                        cr.db.__aexit__ = AsyncMock(return_value=False)
                        cr.db.save_post_post_edge = AsyncMock()
                        cr.db.get_stats = AsyncMock(return_value={"posts": 0, "users": 0})
                        cr.db.save_sample = AsyncMock()
                        cr.json_storage = MagicMock()
                        cr.json_storage.save_sample = AsyncMock(return_value="/tmp/sample.json")
                        cr.edge_builder = EdgeBuilder()
                        cr.session_mgr = mock_sm
                        cr.proxy_mgr = MagicMock(enabled=False)
                        cr.checkpoint = mock_cp
                        cr.rate_limiter = AdaptiveRateLimiter(min_delay=0.01, max_delay=0.05)
                        return cr


# ─── _get_credentials ─────────────────────────────────────────────────────────

class TestGetCredentials:
    def test_returns_explicit_args(self, crawler):
        email, pw = crawler._get_credentials("user@test.com", "secret123")
        assert email == "user@test.com"
        assert pw == "secret123"

    def test_reads_from_env(self, crawler):
        with patch.dict(os.environ, {"FB_EMAIL": "env@test.com", "FB_PASSWORD": "envpw"}):
            email, pw = crawler._get_credentials()
        assert email == "env@test.com"
        assert pw == "envpw"

    def test_returns_none_when_no_env(self, crawler):
        with patch.dict(os.environ, {}, clear=True):
            # Remove FB_EMAIL / FB_PASSWORD if set
            os.environ.pop("FB_EMAIL", None)
            os.environ.pop("FB_PASSWORD", None)
            email, pw = crawler._get_credentials()
        assert email is None
        assert pw is None

    def test_multi_account_index(self, crawler):
        with patch.dict(os.environ, {"FB_EMAIL_2": "acc2@test.com", "FB_PASSWORD_2": "pw2"}):
            email, pw = crawler._get_credentials(account_index=2)
        assert email == "acc2@test.com"
        assert pw == "pw2"

    def test_explicit_overrides_env(self, crawler):
        with patch.dict(os.environ, {"FB_EMAIL": "env@test.com", "FB_PASSWORD": "envpw"}):
            email, pw = crawler._get_credentials("cli@test.com", "clipw")
        assert email == "cli@test.com"
        assert pw == "clipw"


# ─── _flat_config ─────────────────────────────────────────────────────────────

class TestFlatConfig:
    def test_flat_config_includes_max_comments(self, crawler):
        cfg = crawler._flat_config()
        assert "max_comments" in cfg

    def test_flat_config_with_session(self, crawler):
        session = MagicMock(cookies_file="cookies/s1.json")
        cfg = crawler._flat_config(session)
        assert cfg["cookies_file"] == "cookies/s1.json"


# ─── BanException ─────────────────────────────────────────────────────────────

class TestBanException:
    def test_ban_exception_stores_type(self):
        exc = BanException(BanType.CHECKPOINT)
        assert exc.ban_type == BanType.CHECKPOINT
        assert "checkpoint" in str(exc)


# ─── _run_target: page type ──────────────────────────────────────────────────

class TestRunTargetPage:
    @pytest.mark.asyncio
    async def test_page_target_no_posts(self, crawler):
        context = AsyncMock()
        cfg = {"scraping": {}, "storage": {}}

        async def empty_gen(*args, **kwargs):
            return
            yield  # make it an async generator

        mock_scraper = MagicMock()
        mock_scraper.scrape_page = empty_gen

        target = {"type": "page", "url": "https://www.facebook.com/TestPage", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.PageScraper", return_value=mock_scraper):
            count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0

    @pytest.mark.asyncio
    async def test_page_target_with_posts(self, crawler):
        context = AsyncMock()
        cfg = {"scraping": {}, "storage": {}}

        post = PostNode(
            post_id="post_run_001",
            post_url="https://www.facebook.com/page/posts/post_run_001",
            raw_text="Test content",
        )
        sample = GraphSample(sample_id="sample_run_001")
        sample.post = post

        crawler.checkpoint.is_scraped = MagicMock(return_value=False)

        async def mock_gen(url):
            yield sample

        mock_scraper = MagicMock()
        mock_scraper.scrape_page = mock_gen
        mock_scraper.get_page = AsyncMock(return_value=AsyncMock(
            url="https://www.facebook.com/page/posts/post_run_001"
        ))

        target = {"type": "page", "url": "https://www.facebook.com/TestPage", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.PageScraper", return_value=mock_scraper):
            with patch("src.crawler.BanDetector") as MockBD:
                mock_bd = MagicMock()
                mock_bd.check = AsyncMock(return_value=BanType.NONE)
                MockBD.return_value = mock_bd
                count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 1
        assert len(all_posts) == 1

    @pytest.mark.asyncio
    async def test_skips_already_scraped_post(self, crawler):
        context = AsyncMock()
        cfg = {"scraping": {}, "storage": {}}

        post = PostNode(post_id="already_done", post_url="https://fb.com/p/1", raw_text="t")
        sample = GraphSample(sample_id="s1")
        sample.post = post

        crawler.checkpoint.is_scraped = MagicMock(return_value=True)

        async def mock_gen(url):
            yield sample

        mock_scraper = MagicMock()
        mock_scraper.scrape_page = mock_gen
        mock_scraper.get_page = AsyncMock(return_value=AsyncMock(url="https://www.facebook.com/TestPage"))

        target = {"type": "page", "url": "https://fb.com/TestPage", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.PageScraper", return_value=mock_scraper):
            with patch("src.crawler.BanDetector") as MockBD:
                mock_bd = MagicMock()
                mock_bd.check = AsyncMock(return_value=BanType.NONE)
                MockBD.return_value = mock_bd
                count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0


# ─── _run_target: group type ─────────────────────────────────────────────────

class TestRunTargetGroup:
    @pytest.mark.asyncio
    async def test_group_target_no_posts(self, crawler):
        context = AsyncMock()
        cfg = {}

        async def empty_gen(*args, **kwargs):
            return
            yield

        mock_scraper = MagicMock()
        mock_scraper.scrape_group = empty_gen

        target = {"type": "group", "url": "https://www.facebook.com/groups/test", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.GroupScraper", return_value=mock_scraper):
            count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0


# ─── _run_target: search type ────────────────────────────────────────────────

class TestRunTargetSearch:
    @pytest.mark.asyncio
    async def test_search_target_no_posts(self, crawler):
        context = AsyncMock()
        cfg = {}

        async def empty_gen(*args, **kwargs):
            return
            yield

        mock_scraper = MagicMock()
        mock_scraper.scrape_search = empty_gen

        target = {"type": "search", "query": "test query", "url": "", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.SearchScraper", return_value=mock_scraper):
            count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0


# ─── _run_target: hashtag type ───────────────────────────────────────────────

class TestRunTargetHashtag:
    @pytest.mark.asyncio
    async def test_hashtag_target_no_posts(self, crawler):
        context = AsyncMock()
        cfg = {}

        async def empty_gen(*args, **kwargs):
            return
            yield

        mock_scraper = MagicMock()
        mock_scraper.scrape_hashtag = empty_gen

        target = {"type": "hashtag", "query": "vietnam", "url": "https://fb.com/hashtag/vietnam", "max_posts": 5}
        all_posts = []

        with patch("src.crawler.SearchScraper", return_value=mock_scraper):
            count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0


# ─── _run_target: post type ──────────────────────────────────────────────────

class TestRunTargetPost:
    @pytest.mark.asyncio
    async def test_post_target_no_post_returned(self, crawler):
        context = AsyncMock()
        cfg = {"storage": {}}

        mock_scraper = MagicMock()
        mock_page = AsyncMock()
        mock_scraper.get_page = AsyncMock(return_value=mock_page)

        target = {"type": "post", "url": "https://www.facebook.com/page/posts/123", "max_posts": 1}
        all_posts = []

        with patch("src.crawler.PageScraper", return_value=mock_scraper):
            with patch("src.extractors.post_extractor.PostExtractor") as MockPE:
                mock_pe = MagicMock()
                mock_pe.extract_from_url = AsyncMock(return_value=None)
                MockPE.return_value = mock_pe
                with patch("src.extractors.comment_extractor.CommentExtractor"):
                    with patch("src.extractors.media_extractor.MediaExtractor"):
                        count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 0

    @pytest.mark.asyncio
    async def test_post_target_with_post(self, crawler):
        context = AsyncMock()
        cfg = {"storage": {}}

        post = PostNode(
            post_id="post_direct_001",
            post_url="https://www.facebook.com/page/posts/123",
            author_id="u1",
            author_name="Author",
            raw_text="Direct post",
        )
        crawler.checkpoint.is_scraped = MagicMock(return_value=False)

        mock_scraper = MagicMock()
        mock_page = AsyncMock()
        mock_scraper.get_page = AsyncMock(return_value=mock_page)
        mock_scraper._build_sample = MagicMock(return_value=GraphSample(sample_id="s1"))
        mock_scraper._build_sample.return_value.post = post

        target = {"type": "post", "url": "https://www.facebook.com/page/posts/123", "max_posts": 1}
        all_posts = []

        with patch("src.crawler.PageScraper", return_value=mock_scraper):
            with patch("src.extractors.post_extractor.PostExtractor") as MockPE:
                mock_pe = MagicMock()
                mock_pe.extract_from_url = AsyncMock(return_value=post)
                MockPE.return_value = mock_pe
                with patch("src.extractors.comment_extractor.CommentExtractor") as MockCE:
                    mock_ce = MagicMock()
                    mock_ce.extract_all_comments = AsyncMock(return_value=([], []))
                    MockCE.return_value = mock_ce
                    with patch("src.extractors.media_extractor.MediaExtractor") as MockME:
                        mock_me = MagicMock()
                        mock_me.process_post_media = AsyncMock(return_value=post)
                        MockME.return_value = mock_me
                        count = await crawler._run_target(target, context, cfg, all_posts)
        assert count == 1


# ─── _save_sample ─────────────────────────────────────────────────────────────

class TestSaveSample:
    @pytest.mark.asyncio
    async def test_saves_to_json_and_db(self, crawler):
        sample = GraphSample(sample_id="save_test")
        crawler.json_storage.save_sample = AsyncMock(return_value="/tmp/save_test.json")
        crawler.db.save_sample = AsyncMock()
        await crawler._save_sample(sample)
        crawler.json_storage.save_sample.assert_called_once_with(sample)
        crawler.db.save_sample.assert_called_once_with(sample, json_path="/tmp/save_test.json")


# ─── scrape_targets (integration) ────────────────────────────────────────────

class TestScrapeTargets:
    @pytest.mark.asyncio
    async def test_scrape_empty_targets(self, crawler):
        crawler.checkpoint.set_targets = MagicMock()
        crawler.checkpoint.scraped_count = 0
        crawler.db.__aenter__ = AsyncMock(return_value=crawler.db)
        crawler.db.__aexit__ = AsyncMock(return_value=False)
        crawler.db.get_stats = AsyncMock(return_value={"posts": 0})
        crawler.db.save_post_post_edge = AsyncMock()

        with patch.object(crawler, "_scrape_target_with_recovery", new_callable=AsyncMock):
            with patch("builtins.print"):
                await crawler.scrape_targets(
                    targets=[],
                    email=None,
                    password=None,
                )
        crawler.checkpoint.set_targets.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_scrape_targets_calls_recovery(self, crawler):
        targets = [{"type": "page", "url": "https://fb.com/Page"}]
        crawler.checkpoint.set_targets = MagicMock()
        crawler.checkpoint.scraped_count = 0
        crawler.db.__aenter__ = AsyncMock(return_value=crawler.db)
        crawler.db.__aexit__ = AsyncMock(return_value=False)
        crawler.db.get_stats = AsyncMock(return_value={"posts": 0})
        crawler.db.save_post_post_edge = AsyncMock()

        recovery_calls = []

        async def mock_recovery(target, email, pw, posts):
            recovery_calls.append(target)

        with patch.object(crawler, "_scrape_target_with_recovery", side_effect=mock_recovery):
            with patch("builtins.print"):
                await crawler.scrape_targets(targets=targets, email=None, password=None)
        assert len(recovery_calls) == 1


# ─── _scrape_target_with_recovery ────────────────────────────────────────────

class TestScrapeTargetWithRecovery:
    @pytest.mark.asyncio
    async def test_no_session_returns_early(self, crawler):
        crawler.session_mgr.get_active_session = MagicMock(return_value=None)
        crawler.checkpoint.set_current_target = MagicMock()
        all_posts = []
        target = {"type": "page", "url": "https://fb.com/Page"}
        await crawler._scrape_target_with_recovery(target, None, None, all_posts)
        # Should return without doing anything
        assert all_posts == []

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self, crawler):
        session = MagicMock(
            session_id="s1",
            cookies_file="cookies/session.json",
            requests_today=0,
        )
        crawler.session_mgr.get_active_session = MagicMock(return_value=session)
        crawler.session_mgr.on_success = MagicMock()
        crawler.checkpoint.set_current_target = MagicMock()
        crawler.checkpoint.complete_target = MagicMock()

        bm_mock = AsyncMock()
        context_mock = AsyncMock()
        bm_mock.__aenter__ = AsyncMock(return_value=bm_mock)
        bm_mock.__aexit__ = AsyncMock(return_value=False)
        bm_mock.start = AsyncMock(return_value=context_mock)

        base_scraper = MagicMock()
        base_scraper.ensure_logged_in = AsyncMock(return_value=True)

        all_posts = []
        target = {"type": "page", "url": "https://fb.com/Page", "max_posts": 1}

        with patch("src.crawler.BrowserManager", return_value=bm_mock):
            with patch("src.crawler.PageScraper", return_value=base_scraper):
                with patch.object(crawler, "_run_target", new_callable=AsyncMock, return_value=1):
                    await crawler._scrape_target_with_recovery(target, None, None, all_posts)
        crawler.session_mgr.on_success.assert_called_once()
        crawler.checkpoint.complete_target.assert_called_once()

    @pytest.mark.asyncio
    async def test_ban_exception_triggers_ban_handling(self, crawler):
        session = MagicMock(
            session_id="s1",
            cookies_file="cookies/session.json",
            requests_today=0,
        )
        crawler.session_mgr.get_active_session = MagicMock(return_value=session)
        crawler.session_mgr.on_ban = MagicMock()
        crawler.session_mgr.rotate_session = MagicMock(return_value=None)
        crawler.checkpoint.set_current_target = MagicMock()

        bm_mock = AsyncMock()
        bm_mock.__aenter__ = AsyncMock(return_value=bm_mock)
        bm_mock.__aexit__ = AsyncMock(return_value=False)
        bm_mock.start = AsyncMock(return_value=AsyncMock())

        base_scraper = MagicMock()
        base_scraper.ensure_logged_in = AsyncMock(return_value=True)

        target = {"type": "page", "url": "https://fb.com/Page", "max_posts": 1}

        with patch("src.crawler.BrowserManager", return_value=bm_mock):
            with patch("src.crawler.PageScraper", return_value=base_scraper):
                with patch.object(crawler, "_run_target",
                                  new_callable=AsyncMock,
                                  side_effect=BanException(BanType.ACCOUNT_DISABLED)):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await crawler._scrape_target_with_recovery(target, None, None, [], max_retries=1)
        crawler.session_mgr.on_ban.assert_called_once_with(session, permanent=True)

    @pytest.mark.asyncio
    async def test_generic_exception_retries(self, crawler):
        session = MagicMock(
            session_id="s1",
            cookies_file="cookies/session.json",
            requests_today=0,
        )
        crawler.session_mgr.get_active_session = MagicMock(return_value=session)
        crawler.checkpoint.set_current_target = MagicMock()

        bm_mock = AsyncMock()
        bm_mock.__aenter__ = AsyncMock(return_value=bm_mock)
        bm_mock.__aexit__ = AsyncMock(return_value=False)
        bm_mock.start = AsyncMock(return_value=AsyncMock())

        base_scraper = MagicMock()
        base_scraper.ensure_logged_in = AsyncMock(return_value=True)

        target = {"type": "page", "url": "https://fb.com/Page", "max_posts": 1}
        run_count = 0

        async def run_side_effect(*args, **kwargs):
            nonlocal run_count
            run_count += 1
            raise Exception("Random error")

        with patch("src.crawler.BrowserManager", return_value=bm_mock):
            with patch("src.crawler.PageScraper", return_value=base_scraper):
                with patch.object(crawler, "_run_target", side_effect=run_side_effect):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await crawler._scrape_target_with_recovery(target, None, None, [], max_retries=2)
        assert run_count == 2
