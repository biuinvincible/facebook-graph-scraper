"""
Tests for src/crawler.py — FacebookCrawler.__init__ and _setup_logging.
Covers the constructor which was untested.
"""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from src.crawler import FacebookCrawler


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
        "sessions_dir": "/tmp/cookies_test",
        "checkpoint_file": "/tmp/test_checkpoint.json",
        "checkpoint_flush_every": 100,
    },
    "ocr": {"enabled": False, "lang": "eng"},
    "logging": {"file": "/tmp/logs/test_scraper.log", "level": "DEBUG", "rotation": "1 MB"},
}


class TestFacebookCrawlerInit:
    def test_init_creates_components(self, tmp_path):
        """Test that __init__ creates all required components."""
        config = dict(MINIMAL_CONFIG)
        config["storage"] = {**MINIMAL_CONFIG["storage"], "db_path": str(tmp_path / "test.db")}
        config["protection"] = {
            "sessions_dir": str(tmp_path / "cookies"),
            "checkpoint_file": str(tmp_path / "checkpoint.json"),
            "checkpoint_flush_every": 100,
        }
        config["logging"] = {
            "file": str(tmp_path / "logs" / "test.log"),
            "level": "DEBUG",
            "rotation": "1 MB",
        }
        (tmp_path / "cookies").mkdir(exist_ok=True)

        config_yaml = yaml.dump(config)
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_yaml)

        crawler = FacebookCrawler(str(config_file))

        from src.storage.database import Database
        from src.storage.json_storage import JsonStorage
        from src.graph.edge_builder import EdgeBuilder
        from src.utils.session_manager import SessionManager
        from src.utils.proxy_manager import ProxyManager
        from src.utils.checkpoint import ScrapingCheckpoint
        from src.utils.rate_limiter import AdaptiveRateLimiter

        assert isinstance(crawler.db, Database)
        assert isinstance(crawler.json_storage, JsonStorage)
        assert isinstance(crawler.edge_builder, EdgeBuilder)
        assert isinstance(crawler.session_mgr, SessionManager)
        assert isinstance(crawler.proxy_mgr, ProxyManager)
        assert isinstance(crawler.checkpoint, ScrapingCheckpoint)
        assert isinstance(crawler.rate_limiter, AdaptiveRateLimiter)

    def test_init_sets_config_sections(self, tmp_path):
        """Test that config sections are properly extracted."""
        config = dict(MINIMAL_CONFIG)
        config["protection"] = {
            "sessions_dir": str(tmp_path / "cookies"),
            "checkpoint_file": str(tmp_path / "checkpoint.json"),
            "checkpoint_flush_every": 100,
        }
        config["storage"]["db_path"] = str(tmp_path / "test.db")
        config["logging"]["file"] = str(tmp_path / "logs" / "test.log")
        (tmp_path / "cookies").mkdir(exist_ok=True)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        crawler = FacebookCrawler(str(config_file))

        assert crawler.storage_cfg == config["storage"]
        assert crawler.scraping_cfg == config["scraping"]
        assert crawler.scraper_cfg == config["scraper"]

    def test_setup_logging_creates_log_dir(self, tmp_path):
        """Test that _setup_logging creates log directory."""
        log_dir = tmp_path / "new_logs"
        config = dict(MINIMAL_CONFIG)
        config["protection"] = {
            "sessions_dir": str(tmp_path / "cookies"),
            "checkpoint_file": str(tmp_path / "checkpoint.json"),
            "checkpoint_flush_every": 100,
        }
        config["storage"]["db_path"] = str(tmp_path / "test.db")
        config["logging"] = {
            "file": str(log_dir / "scraper.log"),
            "level": "DEBUG",
            "rotation": "1 MB",
        }
        (tmp_path / "cookies").mkdir(exist_ok=True)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        crawler = FacebookCrawler(str(config_file))

        # Log directory should be created
        assert log_dir.exists()

    def test_init_reads_yaml_config(self, tmp_path):
        """Test that config is loaded from YAML file."""
        config = {**MINIMAL_CONFIG}
        config["protection"] = {
            "sessions_dir": str(tmp_path / "cookies"),
            "checkpoint_file": str(tmp_path / "checkpoint.json"),
            "checkpoint_flush_every": 100,
        }
        config["storage"]["db_path"] = str(tmp_path / "test.db")
        config["logging"]["file"] = str(tmp_path / "logs" / "test.log")
        (tmp_path / "cookies").mkdir(exist_ok=True)

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))

        crawler = FacebookCrawler(str(config_file))
        assert crawler.config is not None
        assert "scraper" in crawler.config
        assert "storage" in crawler.config
