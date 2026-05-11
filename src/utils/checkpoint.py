"""
Checkpoint / Resume system.
Lưu tiến trình scraping để có thể resume sau khi bị ban hoặc crash.
"""
import json
import asyncio
from pathlib import Path
from typing import Set, List, Dict, Any, Optional
from datetime import datetime
from loguru import logger


class ScrapingCheckpoint:
    """
    Lưu danh sách post_id đã scrape để không scrape lại khi resume.
    Tự động flush ra disk sau mỗi N posts.
    """

    def __init__(self, checkpoint_file: str, flush_every: int = 10):
        self.checkpoint_file = Path(checkpoint_file)
        self.flush_every = flush_every
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)

        self._scraped_ids: Set[str] = set()
        self._pending_targets: List[Dict] = []
        self._current_target: Optional[Dict] = None
        self._stats: Dict[str, int] = {
            "total_scraped": 0,
            "total_failed": 0,
            "sessions_started": 0,
        }
        self._dirty_count = 0
        self._load()

    def _load(self):
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file) as f:
                    data = json.load(f)
                self._scraped_ids = set(data.get("scraped_ids", []))
                self._pending_targets = data.get("pending_targets", [])
                self._current_target = data.get("current_target")
                self._stats = data.get("stats", self._stats)
                logger.info(
                    f"Resumed from checkpoint: {len(self._scraped_ids)} already scraped, "
                    f"{len(self._pending_targets)} targets pending"
                )
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e} — starting fresh")

    def save(self, force: bool = False):
        self._dirty_count += 1
        if not force and self._dirty_count < self.flush_every:
            return

        data = {
            "checkpoint_at": datetime.utcnow().isoformat(),
            "scraped_ids": list(self._scraped_ids),
            "pending_targets": self._pending_targets,
            "current_target": self._current_target,
            "stats": self._stats,
        }
        tmp = self.checkpoint_file.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        tmp.replace(self.checkpoint_file)  # atomic write
        self._dirty_count = 0
        logger.debug(f"Checkpoint saved: {len(self._scraped_ids)} posts")

    def mark_scraped(self, post_id: str):
        self._scraped_ids.add(post_id)
        self._stats["total_scraped"] += 1
        self.save()

    def mark_failed(self, post_id: str):
        self._stats["total_failed"] += 1
        self.save()

    def is_scraped(self, post_id: str) -> bool:
        return post_id in self._scraped_ids

    def set_targets(self, targets: List[Dict]):
        self._pending_targets = targets
        self.save(force=True)

    def set_current_target(self, target: Dict):
        self._current_target = target
        self.save(force=True)

    def complete_target(self, target: Dict):
        self._pending_targets = [
            t for t in self._pending_targets
            if t.get("url") != target.get("url") and t.get("query") != target.get("query")
        ]
        self._current_target = None
        self.save(force=True)

    @property
    def scraped_count(self) -> int:
        return len(self._scraped_ids)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "scraped_ids_count": len(self._scraped_ids),
            "pending_targets": len(self._pending_targets),
        }
