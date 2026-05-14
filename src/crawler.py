"""
Main crawler orchestrator với ban recovery, checkpoint resume, session rotation.
"""
import asyncio
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import yaml
from dotenv import load_dotenv
from loguru import logger

load_dotenv()  # đọc .env tự động

from .utils.browser import BrowserManager
from .utils.ban_detector import BanDetector, BanType
from .utils.rate_limiter import AdaptiveRateLimiter
from .utils.session_manager import SessionManager
from .utils.proxy_manager import ProxyManager
from .utils.checkpoint import ScrapingCheckpoint
from .scrapers.page_scraper import PageScraper
from .scrapers.group_scraper import GroupScraper
from .scrapers.search_scraper import SearchScraper
from .storage.database import Database
from .storage.json_storage import JsonStorage
from .graph.edge_builder import EdgeBuilder


class FacebookCrawler:
    """
    Autonomous Facebook content crawler với:
    - Ban detection + auto recovery
    - Exponential backoff khi bị throttle
    - Session/account rotation khi bị ban
    - Checkpoint resume (không scrape lại từ đầu)
    - Proxy rotation (optional)
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.storage_cfg = self.config.get("storage", {})
        self.scraping_cfg = self.config.get("scraping", {})
        self.scraper_cfg = self.config.get("scraper", {})
        protection_cfg = self.config.get("protection", {})

        self.db = Database(self.storage_cfg.get("db_path", "data/facebook_graph.db"))
        self.json_storage = JsonStorage(self.storage_cfg.get("json_dir", "data/json"))
        self.edge_builder = EdgeBuilder()

        # Ban protection components
        self.session_mgr = SessionManager(
            sessions_dir=protection_cfg.get("sessions_dir", "cookies"),
        )
        proxy_cfg = self.scraper_cfg.get("proxy", {})
        self.proxy_mgr = ProxyManager(
            proxy_file=proxy_cfg.get("list_file", "proxies/list.txt"),
            enabled=proxy_cfg.get("enabled", False),
        )
        self.checkpoint = ScrapingCheckpoint(
            checkpoint_file=protection_cfg.get("checkpoint_file", "data/checkpoint.json"),
            flush_every=protection_cfg.get("checkpoint_flush_every", 5),
        )
        self.rate_limiter = AdaptiveRateLimiter(
            min_delay=self.scraper_cfg.get("min_delay", 1.5),
            max_delay=self.scraper_cfg.get("max_delay", 4.0),
        )
        self._setup_logging()

    def _setup_logging(self):
        log_cfg = self.config.get("logging", {})
        log_path = log_cfg.get("file", "logs/scraper.log")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            rotation=log_cfg.get("rotation", "10 MB"),
            level=log_cfg.get("level", "INFO"),
            encoding="utf-8",
        )

    def _flat_config(self, session=None) -> Dict[str, Any]:
        cfg = {}
        cfg.update(self.scraper_cfg)
        cfg.update({"storage": self.storage_cfg})
        cfg.update({"scraping": self.scraping_cfg})
        cfg["max_comments"] = self.scraping_cfg.get("max_comments", 500)
        cfg["max_replies_per_comment"] = self.scraping_cfg.get("max_replies_per_comment", 50)
        cfg["scrape_replies"] = self.scraping_cfg.get("scrape_replies", True)
        cfg["scrape_comments"] = self.scraping_cfg.get("scrape_comments", True)
        cfg["scrape_reactions"] = self.scraping_cfg.get("scrape_reactions", True)
        cfg["download_media"] = self.storage_cfg.get("download_media", True)
        cfg["media_dir"] = self.storage_cfg.get("media_dir", "data/media")
        cfg["max_media_size_mb"] = self.storage_cfg.get("max_media_size_mb", 50)
        ocr_cfg = self.config.get("ocr", {})
        cfg["ocr_enabled"] = ocr_cfg.get("enabled", True)
        cfg["ocr_lang"] = ocr_cfg.get("lang", "vie+eng")
        if session:
            cfg["cookies_file"] = session.cookies_file
        return cfg

    def _get_credentials(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        account_index: int = 1,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Lấy credentials theo thứ tự ưu tiên:
        1. Tham số CLI (--email / --password)
        2. Biến môi trường FB_EMAIL / FB_PASSWORD (từ .env)
        3. FB_EMAIL_2 / FB_PASSWORD_2 cho acc thứ 2, v.v.
        """
        if email and password:
            return email, password

        suffix = "" if account_index == 1 else f"_{account_index}"
        env_email = os.getenv(f"FB_EMAIL{suffix}")
        env_password = os.getenv(f"FB_PASSWORD{suffix}")

        if env_email and env_password:
            logger.info(f"Using credentials from .env (FB_EMAIL{suffix})")
            return env_email, env_password

        return None, None

    async def scrape_targets(
        self,
        targets: List[Dict[str, str]],
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Main entry point. Xử lý tất cả targets với full protection."""
        # Resolve credentials (CLI args → .env fallback)
        email, password = self._get_credentials(email, password)
        if email:
            logger.info("Auto-login enabled (credentials from .env)")
        else:
            logger.info("No credentials provided — using cookies only")

        self.checkpoint.set_targets(targets)
        if self.checkpoint.scraped_count > 0:
            logger.info(f"Resuming: {self.checkpoint.scraped_count} posts already scraped")

        async with self.db:
            all_posts = []
            for target in targets:
                await self._scrape_target_with_recovery(
                    target, email, password, all_posts
                )

            # Build cross-post similarity edges
            valid_posts = [p for p in all_posts if p]
            if len(valid_posts) > 1:
                pp_edges = self.edge_builder.build_post_post_edges(valid_posts)
                for edge in pp_edges:
                    await self.db.save_post_post_edge(edge)
                logger.info(f"Built {len(pp_edges)} post-post similarity edges")

            stats = await self.db.get_stats()
            checkpoint_stats = self.checkpoint.stats
            logger.info(f"Final stats: DB={stats} | Checkpoint={checkpoint_stats}")
            print(f"\n✓ Scraping complete!")
            print(f"  DB:         {stats}")
            print(f"  Checkpoint: {checkpoint_stats}")
            print(f"  Sessions:   {self.session_mgr.status_summary}")

    async def _scrape_target_with_recovery(
        self, target: Dict, email: Optional[str], password: Optional[str],
        all_posts: list, max_retries: int = 3
    ):
        """Scrape 1 target với automatic retry khi bị ban"""
        self.checkpoint.set_current_target(target)

        for attempt in range(max_retries):
            session = self.session_mgr.get_active_session()
            if not session:
                logger.error("No available sessions — stopping")
                return

            # Lấy credentials cho session này (hỗ trợ multi-acc từ .env)
            acc_index = int(session.session_id.replace("s", "").replace("default", "1") or 1)
            acc_email, acc_password = self._get_credentials(email, password, acc_index)

            proxy = self.proxy_mgr.get_proxy() if self.proxy_mgr.enabled else None
            scraper_cfg = self.scraper_cfg.copy()
            if proxy:
                scraper_cfg["proxy"] = {"enabled": True, "server": proxy.server}
            if session:
                scraper_cfg["cookies_file"] = session.cookies_file

            cfg = self._flat_config(session)

            try:
                async with BrowserManager(scraper_cfg) as bm:
                    context = await bm.start()

                    base = PageScraper(context, cfg)
                    logged_in = await base.ensure_logged_in()
                    if not logged_in:
                        # Thử login với credentials của acc này
                        if acc_email and acc_password:
                            logger.info(f"Auto-login: session {session.session_id}")
                            logged_in = await base.login_with_credentials(acc_email, acc_password)
                        if not logged_in:
                            logger.warning(f"Session {session.session_id}: not logged in — scraping public only")

                    # Run scraper
                    scraped_count = await self._run_target(target, context, cfg, all_posts)
                    self.session_mgr.on_success(session)

                    if scraped_count > 0:
                        self.checkpoint.complete_target(target)
                        return  # Success

            except BanException as e:
                logger.error(f"Ban on attempt {attempt+1}/{max_retries}: {e.ban_type.value}")
                self.session_mgr.on_ban(session, permanent=(e.ban_type == BanType.ACCOUNT_DISABLED))

                if e.ban_type == BanType.ACCOUNT_DISABLED:
                    # Chuyển session ngay, không cần đợi
                    new_session = self.session_mgr.rotate_session()
                    if new_session:
                        logger.info(f"Switched to session: {new_session.session_id}")
                    else:
                        logger.error("No more sessions available!")
                        return
                else:
                    # Backoff rồi retry
                    backoff = min(60 * (2 ** attempt), 600)
                    logger.info(f"Backing off {backoff}s before retry...")
                    await asyncio.sleep(backoff)

                    if self.proxy_mgr.enabled:
                        new_proxy = self.proxy_mgr.rotate()
                        if new_proxy:
                            logger.info(f"Rotated to proxy: {new_proxy.proxy_id}")

            except Exception as e:
                logger.error(f"Target error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(30)
                continue

        logger.error(f"Target failed after {max_retries} attempts: {target}")

    async def _run_target(
        self, target: Dict, context, cfg: Dict, all_posts: list
    ) -> int:
        """Chạy scraper cho 1 target, bỏ qua posts đã scrape (checkpoint)"""
        target_type = target.get("type", "page").lower()
        url = target.get("url", "")
        query = target.get("query", url)
        max_p = int(target.get("max_posts", 100))

        count = 0
        ban_detector = BanDetector()

        async def handle_sample(sample):
            nonlocal count
            if not sample.post:
                return
            post_id = sample.post.post_id

            # Skip nếu đã scrape (checkpoint resume)
            if self.checkpoint.is_scraped(post_id):
                logger.debug(f"Skipping already scraped: {post_id}")
                return

            await self._save_sample(sample)
            all_posts.append(sample.post)
            self.checkpoint.mark_scraped(post_id)
            self.rate_limiter.on_success()
            count += 1

        if target_type in ("page", "profile"):
            scraper = PageScraper(context, cfg)
            async for sample in scraper.scrape_page(url):
                await handle_sample(sample)
                # Kiểm tra ban sau mỗi N posts
                if count % 10 == 0:
                    page = await scraper.get_page()
                    ban = await ban_detector.check(page)
                    if ban != BanType.NONE:
                        raise BanException(ban)

        elif target_type == "group":
            scraper = GroupScraper(context, cfg)
            async for sample in scraper.scrape_group(url):
                await handle_sample(sample)

        elif target_type == "search":
            scraper = SearchScraper(context, cfg)
            async for sample in scraper.scrape_search(query, max_posts=max_p):
                await handle_sample(sample)

        elif target_type == "hashtag":
            scraper = SearchScraper(context, cfg)
            tag = query or url.split("/")[-1]
            async for sample in scraper.scrape_hashtag(tag, max_posts=max_p):
                await handle_sample(sample)

        elif target_type == "post":
            scraper = PageScraper(context, cfg)
            page = await scraper.get_page()
            from .extractors.post_extractor import PostExtractor
            from .extractors.comment_extractor import CommentExtractor
            from .extractors.media_extractor import MediaExtractor
            pe = PostExtractor(cfg)
            ce = CommentExtractor(cfg)
            me = MediaExtractor(cfg.get("storage", {}))
            post = await pe.extract_from_url(page, url)
            if post:
                post = await me.process_post_media(post)
                comments, comment_edges = await ce.extract_all_comments(page, post.post_id)
                from .graph.schema import UserNode
                author_node = UserNode(
                    user_id=post.author_id or "",
                    display_name=post.author_name or "",
                ) if post.author_id else None
                sample = scraper._build_sample(post, author_node, comments, comment_edges)
                await handle_sample(sample)

        logger.info(f"Target done: {count} new posts scraped | type={target_type}")
        return count

    async def _save_sample(self, sample):
        json_path = await self.json_storage.save_sample(sample)
        await self.db.save_sample(sample, json_path=json_path)


class BanException(Exception):
    def __init__(self, ban_type: BanType):
        self.ban_type = ban_type
        super().__init__(f"Ban detected: {ban_type.value}")
