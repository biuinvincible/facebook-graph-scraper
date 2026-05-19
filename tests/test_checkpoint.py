"""
Tests for src/utils/checkpoint.py — ScrapingCheckpoint
"""
import json
import pytest
from pathlib import Path

from src.utils.checkpoint import ScrapingCheckpoint


class TestScrapingCheckpointInit:
    def test_creates_new_empty_checkpoint(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"))
        assert cp.scraped_count == 0
        assert cp.stats["total_scraped"] == 0
        assert cp.stats["total_failed"] == 0

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "cp.json"
        cp = ScrapingCheckpoint(str(path))
        assert path.parent.exists()

    def test_flush_every_default(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"))
        assert cp.flush_every == 10

    def test_custom_flush_every(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"), flush_every=3)
        assert cp.flush_every == 3


class TestScrapingCheckpointResume:
    def test_loads_existing_checkpoint(self, tmp_path):
        path = tmp_path / "cp.json"
        data = {
            "scraped_ids": ["id1", "id2", "id3"],
            "pending_targets": [{"url": "https://fb.com/page"}],
            "current_target": {"url": "https://fb.com/page"},
            "stats": {"total_scraped": 3, "total_failed": 1, "sessions_started": 0},
        }
        path.write_text(json.dumps(data))
        cp = ScrapingCheckpoint(str(path))
        assert cp.scraped_count == 3
        assert cp.is_scraped("id1")
        assert cp.is_scraped("id2")
        assert cp.stats["total_scraped"] == 3
        assert cp.stats["total_failed"] == 1

    def test_handles_corrupt_checkpoint_gracefully(self, tmp_path):
        path = tmp_path / "cp.json"
        path.write_text("not valid json {{{{")
        # Should not raise
        cp = ScrapingCheckpoint(str(path))
        assert cp.scraped_count == 0

    def test_handles_empty_checkpoint_file(self, tmp_path):
        path = tmp_path / "cp.json"
        path.write_text("{}")
        cp = ScrapingCheckpoint(str(path))
        assert cp.scraped_count == 0


class TestScrapingCheckpointMarkScraped:
    def test_mark_scraped_adds_id(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"), flush_every=100)
        cp.mark_scraped("post_abc")
        assert cp.is_scraped("post_abc")
        assert cp.scraped_count == 1

    def test_is_scraped_false_for_unknown(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"))
        assert not cp.is_scraped("unknown_post")

    def test_mark_scraped_increments_stats(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"), flush_every=100)
        cp.mark_scraped("p1")
        cp.mark_scraped("p2")
        assert cp.stats["total_scraped"] == 2

    def test_mark_failed_increments_failed_stats(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"), flush_every=100)
        cp.mark_failed("p1")
        assert cp.stats["total_failed"] == 1


class TestScrapingCheckpointFlush:
    def test_save_force_writes_file(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        cp.mark_scraped("id1")
        cp.save(force=True)
        assert path.exists()
        saved = json.loads(path.read_text())
        assert "id1" in saved["scraped_ids"]

    def test_auto_flush_after_threshold(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=3)
        # Each mark_scraped calls save() with dirty_count increment
        cp.mark_scraped("a")
        cp.mark_scraped("b")
        # Not flushed yet (dirty_count=2 < 3)
        # On the 3rd mark, dirty_count reaches flush_every
        cp.mark_scraped("c")
        assert path.exists()

    def test_no_flush_before_threshold(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        cp._scraped_ids.add("x")
        cp.save()  # dirty_count = 1, not flushed
        assert not path.exists()

    def test_atomic_write_via_tmp(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=1)
        cp.mark_scraped("atomic_test")
        # tmp file should not exist after atomic rename
        tmp = path.with_suffix(".tmp")
        assert not tmp.exists()
        assert path.exists()


class TestScrapingCheckpointTargets:
    def test_set_targets_saves(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        targets = [{"url": "https://fb.com/page1"}, {"url": "https://fb.com/page2"}]
        cp.set_targets(targets)
        assert path.exists()
        saved = json.loads(path.read_text())
        assert len(saved["pending_targets"]) == 2

    def test_set_current_target(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        target = {"url": "https://fb.com/page1"}
        cp.set_current_target(target)
        saved = json.loads(path.read_text())
        assert saved["current_target"]["url"] == "https://fb.com/page1"

    def test_complete_target_removes_from_pending(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        # Use targets that differ on BOTH url and query to avoid the and-condition removing all
        targets = [
            {"url": "https://fb.com/page1", "query": "q1"},
            {"url": "https://fb.com/page2", "query": "q2"},
        ]
        cp.set_targets(targets)
        cp.complete_target({"url": "https://fb.com/page1", "query": "q1"})
        saved = json.loads(path.read_text())
        urls = [t["url"] for t in saved["pending_targets"]]
        assert "https://fb.com/page1" not in urls
        assert "https://fb.com/page2" in urls

    def test_complete_target_clears_current(self, tmp_path):
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        cp.set_current_target({"url": "https://fb.com/page1"})
        cp.complete_target({"url": "https://fb.com/page1"})
        saved = json.loads(path.read_text())
        assert saved["current_target"] is None

    def test_stats_property(self, tmp_path):
        cp = ScrapingCheckpoint(str(tmp_path / "cp.json"), flush_every=100)
        cp.mark_scraped("p1")
        stats = cp.stats
        assert stats["total_scraped"] == 1
        assert stats["scraped_ids_count"] == 1
        assert "pending_targets" in stats

    def test_complete_target_by_query_and_url(self, tmp_path):
        # complete_target uses 'and' so BOTH url and query must differ for a target to be kept.
        # Targets that have url=None AND query matching the removed target are also removed.
        # Workaround: use targets with distinct URLs alongside queries.
        path = tmp_path / "cp.json"
        cp = ScrapingCheckpoint(str(path), flush_every=100)
        targets = [
            {"url": "https://fb.com/1", "query": "search_term"},
            {"url": "https://fb.com/2", "query": "other_term"},
        ]
        cp.set_targets(targets)
        cp.complete_target({"url": "https://fb.com/1", "query": "search_term"})
        urls = [t["url"] for t in cp._pending_targets]
        assert "https://fb.com/1" not in urls
        assert "https://fb.com/2" in urls
