"""
Supabase sync cho scraped_ids và target_urls.

scraped_ids: dedup giữa các máy — máy nào scrape post rồi thì đánh dấu lên đây.
target_urls: chia sẻ danh sách URLs cần crawl — máy collect push lên, máy crawl pull về.

Flow scraped_ids:
  - Khi khởi động: fetch toàn bộ scraped_ids → merge vào local set
  - Khi mark_scraped(): thêm vào queue, flush mỗi N posts

Flow target_urls:
  - collect_urls.py push URLs sau khi thu thập xong
  - Máy crawl: pull_target_urls() → lưu local YAML → chạy scraper
"""
import os
import httpx
from typing import Set, List, Dict, Optional
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

    # ── target_urls ───────────────────────────────────────────────────────────

    def push_urls(self, items: List[Dict]) -> bool:
        """Push [{url, category}] lên target_urls. Duplicate bị ignore."""
        if not items:
            return True
        try:
            for i in range(0, len(items), self.BATCH_SIZE):
                batch = items[i:i + self.BATCH_SIZE]
                r = httpx.post(
                    f"{self.base_url}/target_urls",
                    json=batch,
                    headers=self.headers,
                    timeout=30,
                )
                r.raise_for_status()
            logger.info(f"[Supabase] Pushed {len(items)} target URLs")
            return True
        except Exception as e:
            logger.warning(f"[Supabase] push_urls failed: {e}")
            return False

    def pull_target_urls(self, exclude_scraped: bool = True) -> List[Dict]:
        """
        Pull toàn bộ target_urls chưa scraped.
        Nếu exclude_scraped=True, lọc bỏ những URL có post_id trong scraped_ids.
        Trả về [{url, category}].
        """
        items: List[Dict] = []
        offset = 0
        limit = 1000
        try:
            while True:
                r = httpx.get(
                    f"{self.base_url}/target_urls",
                    params={"select": "url,category", "limit": limit, "offset": offset},
                    headers=self.headers,
                    timeout=30,
                )
                r.raise_for_status()
                rows = r.json()
                if not rows:
                    break
                items.extend(rows)
                if len(rows) < limit:
                    break
                offset += limit
            logger.info(f"[Supabase] Pulled {len(items)} target URLs")
        except Exception as e:
            logger.warning(f"[Supabase] pull_target_urls failed: {e}")
        return items

    def count_target_urls(self) -> Optional[int]:
        """Trả về tổng số URLs trong target_urls table."""
        try:
            r = httpx.get(
                f"{self.base_url}/target_urls",
                params={"select": "url", "limit": 1},
                headers={**self.headers, "Prefer": "count=exact"},
                timeout=10,
            )
            r.raise_for_status()
            content_range = r.headers.get("Content-Range", "")
            if "/" in content_range:
                return int(content_range.split("/")[1])
        except Exception as e:
            logger.warning(f"[Supabase] count_target_urls failed: {e}")
        return None


def from_env() -> "SupabaseSync | None":
    """Tạo SupabaseSync từ .env. Trả None nếu chưa cấu hình."""
    url = os.environ.get("supabase_db", "").strip()
    key = os.environ.get("supabase_key", "").strip()
    if url and key:
        return SupabaseSync(url, key)
    return None
