"""
Tests for src/extractors/comment_extractor.py
- _parse_relative_time() module-level function (all 7 VN time units + None case)
- CommentExtractor.__init__
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.extractors.comment_extractor import _parse_relative_time, CommentExtractor


# ─── _parse_relative_time ────────────────────────────────────────────────────

class TestParseRelativeTime:
    """Test all 7 VN time units and the None (no-match) case."""

    def _approx_iso(self, result: str, expected_dt: datetime, tolerance_seconds: int = 5) -> bool:
        """Check that result ISO string is within tolerance of expected_dt."""
        result_dt = datetime.fromisoformat(result)
        diff = abs((result_dt - expected_dt).total_seconds())
        return diff <= tolerance_seconds

    def test_giay(self):
        """giây = seconds"""
        result = _parse_relative_time("30 giây trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(seconds=30)
        assert self._approx_iso(result, expected)

    def test_phut(self):
        """phút = minutes"""
        result = _parse_relative_time("5 phút trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_gio(self):
        """giờ = hours"""
        result = _parse_relative_time("2 giờ trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_ngay(self):
        """ngày = days"""
        result = _parse_relative_time("3 ngày trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(days=3)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_tuan(self):
        """tuần = weeks"""
        result = _parse_relative_time("1 tuần trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(weeks=1)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_thang(self):
        """tháng = months (approx 30 days each)"""
        result = _parse_relative_time("2 tháng trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(days=60)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_nam(self):
        """năm = years (approx 365 days each)"""
        result = _parse_relative_time("1 năm trước")
        assert result is not None
        expected = datetime.now(tz=timezone.utc) - timedelta(days=365)
        assert self._approx_iso(result, expected, tolerance_seconds=10)

    def test_no_match_returns_none(self):
        result = _parse_relative_time("some random text without time")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_relative_time("")
        assert result is None

    def test_embedded_in_longer_text(self):
        """Should extract time even when embedded in a sentence."""
        result = _parse_relative_time("Bình luận của Nguyễn Văn A vào 10 giờ trước")
        assert result is not None

    def test_returns_iso_string(self):
        result = _parse_relative_time("1 giờ trước")
        assert isinstance(result, str)
        # Should be parseable as ISO date
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None  # timezone-aware

    def test_large_number(self):
        result = _parse_relative_time("365 ngày trước")
        assert result is not None


# ─── CommentExtractor.__init__ ────────────────────────────────────────────────

class TestCommentExtractorInit:
    def test_defaults(self):
        ext = CommentExtractor({})
        assert ext.max_comments == 500
        assert ext.max_replies == 50
        assert ext.scrape_replies is True

    def test_custom_config(self):
        config = {
            "max_comments": 100,
            "max_replies_per_comment": 10,
            "scrape_replies": False,
        }
        ext = CommentExtractor(config)
        assert ext.max_comments == 100
        assert ext.max_replies == 10
        assert ext.scrape_replies is False

    def test_cfg_stored(self):
        config = {"max_comments": 200, "custom_key": "val"}
        ext = CommentExtractor(config)
        assert ext.cfg is config
        assert ext.cfg.get("custom_key") == "val"

    def test_partial_config(self):
        ext = CommentExtractor({"max_comments": 50})
        assert ext.max_comments == 50
        assert ext.max_replies == 50  # default
        assert ext.scrape_replies is True  # default
