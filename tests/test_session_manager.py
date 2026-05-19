"""
Tests for src/utils/session_manager.py — SessionManager + SessionInfo
"""
import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from src.utils.session_manager import SessionManager, SessionInfo


class TestSessionInfo:
    def test_default_status_active(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json")
        assert s.status == "active"
        assert s.is_available()

    def test_banned_not_available(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json", status="banned")
        assert not s.is_available()

    def test_exhausted_not_available(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json", status="exhausted")
        assert not s.is_available()

    def test_max_requests_exhaustion(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json",
                        requests_today=500, max_requests_per_day=500)
        assert not s.is_available()

    def test_cooldown_expired_becomes_active(self):
        past = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        s = SessionInfo(session_id="s1", cookies_file="c.json",
                        status="cooldown", cooldown_until=past)
        assert s.is_available()
        assert s.status == "active"

    def test_cooldown_not_expired_unavailable(self):
        future = (datetime.utcnow() + timedelta(hours=2)).isoformat()
        s = SessionInfo(session_id="s1", cookies_file="c.json",
                        status="cooldown", cooldown_until=future)
        assert not s.is_available()

    def test_mark_banned(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json")
        s.mark_banned()
        assert s.status == "banned"
        assert s.ban_count == 1

    def test_mark_banned_increments_count(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json", ban_count=2)
        s.mark_banned()
        assert s.ban_count == 3

    def test_put_on_cooldown(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json")
        s.put_on_cooldown(minutes=30)
        assert s.status == "cooldown"
        assert s.cooldown_until is not None
        # cooldown_until should be ~30 min in the future
        until = datetime.fromisoformat(s.cooldown_until)
        diff = (until - datetime.utcnow()).total_seconds()
        assert 29 * 60 <= diff <= 31 * 60

    def test_record_request(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json")
        s.record_request()
        assert s.requests_today == 1
        assert s.last_used is not None

    def test_to_dict(self):
        s = SessionInfo(session_id="s1", cookies_file="c.json", email="a@b.com")
        d = s.to_dict()
        assert d["session_id"] == "s1"
        assert d["cookies_file"] == "c.json"
        assert d["email"] == "a@b.com"


class TestSessionManagerDiscovery:
    def test_single_session_mode_when_no_files(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        assert len(mgr.sessions) == 1
        assert mgr.sessions[0].session_id == "default"

    def test_discovers_session_files(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        (sessions_dir / "session1.json").write_text("{}")
        (sessions_dir / "session2.json").write_text("{}")
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        assert len(mgr.sessions) == 2

    def test_ignores_sessions_state_file(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        (sessions_dir / "session1.json").write_text("{}")
        (sessions_dir / "sessions_state.json").write_text('{"sessions":[]}')
        # state_file points to a non-existent path so it triggers discovery
        state_file = tmp_path / "nonexistent_state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        # Only session1.json should be found (sessions_state.json is skipped)
        assert len(mgr.sessions) == 1


class TestSessionManagerLoadState:
    def test_loads_state_file(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        state_data = {
            "sessions": [
                {
                    "session_id": "s1",
                    "cookies_file": "cookies/session1.json",
                    "email": "test@test.com",
                    "status": "active",
                    "ban_count": 0,
                    "last_used": None,
                    "cooldown_until": None,
                    "requests_today": 5,
                    "max_requests_per_day": 500,
                }
            ]
        }
        state_file.write_text(json.dumps(state_data))
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        assert len(mgr.sessions) == 1
        assert mgr.sessions[0].session_id == "s1"
        assert mgr.sessions[0].requests_today == 5

    def test_corrupted_state_falls_back_to_discovery(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        (sessions_dir / "session1.json").write_text("{}")
        state_file = tmp_path / "state.json"
        state_file.write_text("not valid json")
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        # Falls back to discovery
        assert len(mgr.sessions) == 1


class TestSessionManagerGetActive:
    def _make_manager(self, tmp_path, sessions):
        mgr = SessionManager.__new__(SessionManager)
        mgr.sessions_dir = tmp_path
        mgr.state_file = tmp_path / "state.json"
        mgr.sessions = sessions
        mgr._current_idx = 0
        return mgr

    def test_get_active_returns_least_used(self, tmp_path):
        s1 = SessionInfo("s1", "c1.json", requests_today=10)
        s2 = SessionInfo("s2", "c2.json", requests_today=3)
        mgr = self._make_manager(tmp_path, [s1, s2])
        active = mgr.get_active_session()
        assert active == s2

    def test_get_active_returns_none_when_all_banned(self, tmp_path):
        s1 = SessionInfo("s1", "c1.json", status="banned")
        s2 = SessionInfo("s2", "c2.json", status="banned")
        mgr = self._make_manager(tmp_path, [s1, s2])
        assert mgr.get_active_session() is None


class TestSessionManagerRotate:
    def _make_manager(self, tmp_path, sessions):
        mgr = SessionManager.__new__(SessionManager)
        mgr.sessions_dir = tmp_path
        mgr.state_file = tmp_path / "state.json"
        mgr.sessions = sessions
        mgr._current_idx = 0
        return mgr

    def test_rotate_returns_different_session(self, tmp_path):
        s1 = SessionInfo("s1", "c1.json", requests_today=1)
        s2 = SessionInfo("s2", "c2.json", requests_today=5)
        mgr = self._make_manager(tmp_path, [s1, s2])
        # get_active returns s1 (least used)
        rotated = mgr.rotate_session()
        # rotate should return s2 (not current)
        assert rotated == s2

    def test_rotate_returns_current_if_only_one(self, tmp_path):
        s1 = SessionInfo("s1", "c1.json")
        mgr = self._make_manager(tmp_path, [s1])
        result = mgr.rotate_session()
        assert result == s1

    def test_rotate_returns_none_when_all_banned(self, tmp_path):
        s1 = SessionInfo("s1", "c1.json", status="banned")
        mgr = self._make_manager(tmp_path, [s1])
        assert mgr.rotate_session() is None


class TestSessionManagerOnBanSuccess:
    def test_on_ban_permanent(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        s = mgr.sessions[0]
        mgr.on_ban(s, permanent=True)
        assert s.status == "banned"
        assert state_file.exists()

    def test_on_ban_temp_puts_on_cooldown(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        s = mgr.sessions[0]
        mgr.on_ban(s, permanent=False)
        assert s.status == "cooldown"

    def test_on_success_records_request(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        s = mgr.sessions[0]
        for _ in range(10):
            mgr.on_success(s)
        assert s.requests_today == 10
        # After 10 requests, state should be saved
        assert state_file.exists()

    def test_on_throttle_puts_on_cooldown(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        s = mgr.sessions[0]
        mgr.on_throttle(s)
        assert s.status == "cooldown"


class TestSessionManagerStatusSummary:
    def test_status_summary(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        summary = mgr.status_summary
        assert "total" in summary
        assert "active" in summary
        assert "banned" in summary
        assert "cooldown" in summary
        assert "sessions" in summary
        assert summary["total"] == 1

    def test_save_state(self, tmp_path):
        sessions_dir = tmp_path / "cookies"
        sessions_dir.mkdir()
        state_file = tmp_path / "state.json"
        mgr = SessionManager(
            sessions_dir=str(sessions_dir),
            state_file=str(state_file),
        )
        mgr.save_state()
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "sessions" in data
