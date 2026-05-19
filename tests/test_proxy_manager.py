"""
Tests for src/utils/proxy_manager.py — ProxyManager and ProxyInfo
"""
import pytest
import time
from pathlib import Path
from unittest.mock import patch

from src.utils.proxy_manager import ProxyManager, ProxyInfo


# ─── ProxyInfo ────────────────────────────────────────────────────────────────

class TestProxyInfo:
    def test_is_available_when_new(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        assert proxy.is_available is True

    def test_is_not_available_when_dead(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1", is_dead=True)
        assert proxy.is_available is False

    def test_is_not_available_when_too_many_failures(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1", failures=5)
        assert proxy.is_available is False

    def test_record_failure_increments(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        proxy.record_failure()
        assert proxy.failures == 1

    def test_record_failure_marks_dead_at_5(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        for _ in range(5):
            proxy.record_failure()
        assert proxy.is_dead is True

    def test_record_success_decrements_failures(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1", failures=3)
        proxy.record_success()
        assert proxy.failures == 2

    def test_record_success_updates_last_used(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        before = time.time()
        proxy.record_success()
        assert proxy.last_used >= before

    def test_record_success_updates_latency(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        proxy.record_success(latency_ms=100.0)
        assert proxy.avg_latency_ms > 0

    def test_record_success_doesnt_go_below_zero(self):
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1", failures=0)
        proxy.record_success()
        assert proxy.failures == 0

    def test_to_playwright_config(self):
        proxy = ProxyInfo(server="http://user:pass@proxy:8080", proxy_id="p1")
        config = proxy.to_playwright_config()
        assert config == {"server": "http://user:pass@proxy:8080"}


# ─── ProxyManager.__init__ ────────────────────────────────────────────────────

class TestProxyManagerInit:
    def test_disabled_when_enabled_false(self):
        pm = ProxyManager(enabled=False)
        assert pm.enabled is False
        assert pm.proxies == []

    def test_enabled_but_no_file(self, tmp_path):
        pm = ProxyManager(proxy_file=str(tmp_path / "no_file.txt"), enabled=True)
        assert pm.enabled is False  # disabled because file not found
        assert pm.proxies == []

    def test_loads_proxies_from_file(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("http://proxy1:8080\nhttp://proxy2:8081\n# comment\n")
        pm = ProxyManager(proxy_file=str(proxy_file), enabled=True)
        assert len(pm.proxies) == 2
        assert pm.proxies[0].server == "http://proxy1:8080"
        assert pm.proxies[1].server == "http://proxy2:8081"

    def test_skips_comments_in_file(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("# this is a comment\nhttp://proxy1:8080\n\n")
        pm = ProxyManager(proxy_file=str(proxy_file), enabled=True)
        assert len(pm.proxies) == 1

    def test_assigns_proxy_ids(self, tmp_path):
        proxy_file = tmp_path / "proxies.txt"
        proxy_file.write_text("http://proxy1:8080\nhttp://proxy2:8081\n")
        pm = ProxyManager(proxy_file=str(proxy_file), enabled=True)
        assert pm.proxies[0].proxy_id == "p1"
        assert pm.proxies[1].proxy_id == "p2"


# ─── add_proxy ────────────────────────────────────────────────────────────────

class TestAddProxy:
    def test_adds_proxy_to_list(self):
        pm = ProxyManager(enabled=False)
        pm.add_proxy("http://new-proxy:8080")
        assert len(pm.proxies) == 1
        assert pm.proxies[0].server == "http://new-proxy:8080"

    def test_assigns_incrementing_ids(self):
        pm = ProxyManager(enabled=False)
        pm.add_proxy("http://proxy1:8080")
        pm.add_proxy("http://proxy2:8081")
        assert pm.proxies[0].proxy_id == "p1"
        assert pm.proxies[1].proxy_id == "p2"


# ─── get_proxy ────────────────────────────────────────────────────────────────

class TestGetProxy:
    def test_returns_none_when_disabled(self):
        pm = ProxyManager(enabled=False)
        pm.add_proxy("http://proxy:8080")
        result = pm.get_proxy()
        assert result is None

    def test_returns_none_when_no_proxies(self):
        pm = ProxyManager(enabled=True)
        result = pm.get_proxy()
        assert result is None

    def test_returns_available_proxy(self):
        pm = ProxyManager(enabled=False)
        pm.enabled = True  # manually enable after init
        pm.add_proxy("http://proxy1:8080")
        result = pm.get_proxy()
        assert result is not None
        assert result.server == "http://proxy1:8080"

    def test_returns_none_when_all_dead(self):
        pm = ProxyManager(enabled=False)
        pm.enabled = True
        pm.add_proxy("http://proxy1:8080")
        pm.proxies[0].is_dead = True
        result = pm.get_proxy()
        assert result is None

    def test_prefers_proxy_with_fewer_failures(self):
        pm = ProxyManager(enabled=False)
        pm.enabled = True
        pm.add_proxy("http://proxy1:8080")
        pm.add_proxy("http://proxy2:8081")
        pm.proxies[0].failures = 3
        pm.proxies[1].failures = 0
        result = pm.get_proxy()
        assert result.server == "http://proxy2:8081"


# ─── rotate ───────────────────────────────────────────────────────────────────

class TestRotate:
    def test_returns_none_when_disabled(self):
        pm = ProxyManager(enabled=False)
        pm.add_proxy("http://proxy:8080")
        result = pm.rotate()
        assert result is None

    def test_returns_none_when_no_proxies(self):
        pm = ProxyManager(enabled=True)
        result = pm.rotate()
        assert result is None

    def test_returns_available_proxy(self):
        pm = ProxyManager(enabled=False)
        pm.enabled = True
        pm.add_proxy("http://proxy1:8080")
        result = pm.rotate()
        assert result is not None

    def test_returns_none_when_all_dead(self):
        pm = ProxyManager(enabled=False)
        pm.enabled = True
        pm.add_proxy("http://proxy1:8080")
        pm.proxies[0].is_dead = True
        result = pm.rotate()
        assert result is None


# ─── mark_dead ────────────────────────────────────────────────────────────────

class TestMarkDead:
    def test_marks_proxy_as_dead(self):
        pm = ProxyManager(enabled=False)
        proxy = ProxyInfo(server="http://proxy:8080", proxy_id="p1")
        pm.proxies.append(proxy)
        pm.mark_dead(proxy)
        assert proxy.is_dead is True


# ─── stats ────────────────────────────────────────────────────────────────────

class TestProxyStats:
    def test_stats_empty(self):
        pm = ProxyManager(enabled=False)
        stats = pm.stats
        assert stats["total"] == 0
        assert stats["available"] == 0
        assert stats["dead"] == 0

    def test_stats_with_proxies(self):
        pm = ProxyManager(enabled=True)
        pm.add_proxy("http://proxy1:8080")
        pm.add_proxy("http://proxy2:8081")
        pm.proxies[1].is_dead = True
        stats = pm.stats
        assert stats["total"] == 2
        assert stats["available"] == 1
        assert stats["dead"] == 1
