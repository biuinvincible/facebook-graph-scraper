"""
Supabase sync cho scraped_ids — cho phép nhiều máy crawl song song không trùng post.

Flow:
  - Khi khởi động: fetch toàn bộ scraped_ids từ Supabase → merge vào local set
  - Khi mark_scraped(): thêm vào local set + queue
  - Mỗi flush_every posts: push queue lên Supabase theo batch
"""
import os
import httpx
from typing import Set, List
from loguru import logger


class SupabaseSync:
    BATCH_SIZE = 500  # rows per insert request

    def __init__(self, url: str, key: str):
        # url có thể là "https://xxx.supabase.co/rest/v1/" hoặc "https://xxx.supabase.co"
        base = url.rstrip("/")
        if not base.endswith("/rest/v1"):
            base = base + "/rest/v1"
        self.base_url = base
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates",
        }
        self._queue: List[str] = []

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetch_all(self) -> Set[str]:
        """Download toàn bộ scraped_ids từ Supabase. Dùng pagination 1000 rows/page."""
        ids: Set[str] = set()
        offset = 0
        limit = 1000
        try:
            while True:
                r = httpx.get(
                    f"{self.base_url}/scraped_ids",
                    params={"select": "post_id", "limit": limit, "offset": offset},
                    headers=self.headers,
                    timeout=30,
                )
                r.raise_for_status()
                rows = r.json()
                if not rows:
                    break
                for row in rows:
                    ids.add(row["post_id"])
                if len(rows) < limit:
                    break
                offset += limit
            logger.info(f"[Supabase] Fetched {len(ids)} scraped_ids")
        except Exception as e:
            logger.warning(f"[Supabase] fetch_all failed: {e} — dùng local checkpoint")
        return ids

    # ── Push ──────────────────────────────────────────────────────────────────

    def push(self, post_ids: List[str]) -> bool:
        """Bulk insert post_ids. Duplicate bị ignore (PRIMARY KEY)."""
        if not post_ids:
            return True
        try:
            for i in range(0, len(post_ids), self.BATCH_SIZE):
                batch = post_ids[i:i + self.BATCH_SIZE]
                payload = [{"post_id": pid} for pid in batch]
                r = httpx.post(
                    f"{self.base_url}/scraped_ids",
                    json=payload,
                    headers=self.headers,
                    timeout=30,
                )
                r.raise_for_status()
            logger.debug(f"[Supabase] Pushed {len(post_ids)} ids")
            return True
        except Exception as e:
            logger.warning(f"[Supabase] push failed: {e}")
            return False

    # ── Queue helpers ─────────────────────────────────────────────────────────

    def enqueue(self, post_id: str):
        self._queue.append(post_id)

    def flush_queue(self) -> bool:
        if not self._queue:
            return True
        ok = self.push(self._queue)
        if ok:
            self._queue.clear()
        return ok


def from_env() -> "SupabaseSync | None":
    """Tạo SupabaseSync từ .env. Trả None nếu chưa cấu hình."""
    url = os.environ.get("supabase_db", "").strip()
    key = os.environ.get("supabase_key", "").strip()
    if url and key:
        return SupabaseSync(url, key)
    return None
