"""
Session/Account rotation manager.
Quản lý nhiều tài khoản Facebook — khi 1 bị ban thì tự động chuyển sang tài khoản khác.
"""
import json
import asyncio
import random
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from loguru import logger


@dataclass
class SessionInfo:
    session_id: str
    cookies_file: str
    email: Optional[str] = None
    status: str = "active"          # active, banned, cooldown, exhausted
    ban_count: int = 0
    last_used: Optional[str] = None
    cooldown_until: Optional[str] = None
    requests_today: int = 0
    max_requests_per_day: int = 500

    def is_available(self) -> bool:
        if self.status == "banned":
            return False
        if self.status == "exhausted":
            return False
        if self.status == "cooldown":
            if self.cooldown_until:
                if datetime.utcnow().isoformat() < self.cooldown_until:
                    return False
            self.status = "active"
        if self.requests_today >= self.max_requests_per_day:
            return False
        return True

    def put_on_cooldown(self, minutes: int = 30):
        self.status = "cooldown"
        until = datetime.utcnow() + timedelta(minutes=minutes)
        self.cooldown_until = until.isoformat()
        logger.warning(f"Session {self.session_id} on cooldown for {minutes}m (until {until.strftime('%H:%M')})")

    def mark_banned(self):
        self.status = "banned"
        self.ban_count += 1
        logger.error(f"Session {self.session_id} BANNED (total bans: {self.ban_count})")

    def record_request(self):
        self.requests_today += 1
        self.last_used = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class SessionManager:
    """
    Quản lý pool nhiều sessions.

    Cách dùng:
    1. Tạo file cookies cho từng tài khoản: cookies/session_1.json, cookies/session_2.json
    2. SessionManager tự xoay vòng khi cần
    """

    def __init__(self, sessions_dir: str = "cookies", state_file: str = "cookies/sessions_state.json"):
        self.sessions_dir = Path(sessions_dir)
        self.state_file = Path(state_file)
        self.sessions: List[SessionInfo] = []
        self._current_idx = 0
        self._load_or_discover()

    def _load_or_discover(self):
        """Load state file hoặc tự phát hiện các cookies file có sẵn"""
        if self.state_file.exists():
            self._load_state()
        else:
            self._discover_sessions()

    def _discover_sessions(self):
        """Tự quét thư mục cookies/ tìm các session files"""
        cookie_files = sorted(self.sessions_dir.glob("session*.json"))
        for i, f in enumerate(cookie_files):
            if f.name == "sessions_state.json":
                continue
            session = SessionInfo(
                session_id=f"s{i+1}",
                cookies_file=str(f),
            )
            self.sessions.append(session)

        if self.sessions:
            logger.info(f"Discovered {len(self.sessions)} sessions: {[s.session_id for s in self.sessions]}")
        else:
            # Tạo 1 session mặc định (single-account mode)
            default = SessionInfo(
                session_id="default",
                cookies_file="cookies/session.json",
            )
            self.sessions.append(default)
            logger.info("Single session mode (1 account)")

    def _load_state(self):
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            for s_data in data.get("sessions", []):
                self.sessions.append(SessionInfo(**s_data))
            logger.info(f"Loaded {len(self.sessions)} sessions from state file")
        except Exception as e:
            logger.warning(f"Failed to load sessions state: {e}")
            self._discover_sessions()

    def save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"sessions": [s.to_dict() for s in self.sessions]}
        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_active_session(self) -> Optional[SessionInfo]:
        """Lấy session hiện tại đang active"""
        available = [s for s in self.sessions if s.is_available()]
        if not available:
            logger.error("NO available sessions! Tất cả đều bị ban hoặc cooldown.")
            return None

        # Dùng session có ít requests nhất hôm nay
        return min(available, key=lambda s: s.requests_today)

    def rotate_session(self) -> Optional[SessionInfo]:
        """Xoay sang session tiếp theo"""
        available = [s for s in self.sessions if s.is_available()]
        if not available:
            return None

        # Loại bỏ session hiện tại nếu có thể
        current = self.get_active_session()
        others = [s for s in available if s != current]
        if others:
            chosen = random.choice(others)
            logger.info(f"Rotated to session: {chosen.session_id} ({chosen.requests_today} req today)")
            return chosen
        return current

    def on_ban(self, session: SessionInfo, permanent: bool = False):
        if permanent:
            session.mark_banned()
        else:
            session.put_on_cooldown(minutes=random.randint(30, 90))
        self.save_state()

    def on_throttle(self, session: SessionInfo):
        session.put_on_cooldown(minutes=random.randint(10, 20))
        self.save_state()

    def on_success(self, session: SessionInfo):
        session.record_request()
        # Save periodically
        if session.requests_today % 10 == 0:
            self.save_state()

    @property
    def status_summary(self) -> Dict[str, Any]:
        return {
            "total": len(self.sessions),
            "active": sum(1 for s in self.sessions if s.is_available()),
            "banned": sum(1 for s in self.sessions if s.status == "banned"),
            "cooldown": sum(1 for s in self.sessions if s.status == "cooldown"),
            "sessions": [
                {
                    "id": s.session_id,
                    "status": s.status,
                    "requests_today": s.requests_today,
                    "ban_count": s.ban_count,
                }
                for s in self.sessions
            ],
        }
