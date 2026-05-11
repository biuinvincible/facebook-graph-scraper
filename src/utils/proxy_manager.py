"""
Proxy rotation manager.
Hỗ trợ: file danh sách proxy, hoặc API từ nhà cung cấp proxy.
"""
import asyncio
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class ProxyInfo:
    server: str           # http://host:port hoặc http://user:pass@host:port
    proxy_id: str = ""
    failures: int = 0
    last_used: float = 0
    is_dead: bool = False
    avg_latency_ms: float = 0

    def to_playwright_config(self) -> Dict:
        return {"server": self.server}

    @property
    def is_available(self) -> bool:
        return not self.is_dead and self.failures < 5

    def record_failure(self):
        self.failures += 1
        if self.failures >= 5:
            self.is_dead = True
            logger.warning(f"Proxy {self.proxy_id} marked dead after {self.failures} failures")

    def record_success(self, latency_ms: float = 0):
        self.failures = max(0, self.failures - 1)
        self.last_used = time.time()
        if latency_ms:
            # Rolling average
            self.avg_latency_ms = (self.avg_latency_ms * 0.8 + latency_ms * 0.2)


class ProxyManager:
    """
    Proxy rotation với health tracking.

    Để dùng:
    1. Tạo file proxies/list.txt với mỗi dòng là 1 proxy:
       http://user:pass@ip:port
       socks5://user:pass@ip:port
    2. Hoặc set proxy_list trong config.yaml
    """

    def __init__(self, proxy_file: str = "proxies/list.txt", enabled: bool = False):
        self.enabled = enabled
        self.proxies: List[ProxyInfo] = []
        self._current_idx = 0

        if enabled and proxy_file:
            self._load_from_file(proxy_file)

    def _load_from_file(self, filepath: str):
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"Proxy file not found: {filepath} — running without proxy")
            self.enabled = False
            return

        with open(path) as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

        for i, line in enumerate(lines):
            proxy = ProxyInfo(server=line, proxy_id=f"p{i+1}")
            self.proxies.append(proxy)

        logger.info(f"Loaded {len(self.proxies)} proxies from {filepath}")

    def add_proxy(self, server: str):
        pid = f"p{len(self.proxies)+1}"
        self.proxies.append(ProxyInfo(server=server, proxy_id=pid))

    def get_proxy(self) -> Optional[ProxyInfo]:
        """Lấy proxy tốt nhất hiện tại"""
        if not self.enabled or not self.proxies:
            return None

        available = [p for p in self.proxies if p.is_available]
        if not available:
            logger.error("All proxies are dead!")
            return None

        # Chọn proxy ít dùng nhất gần đây + ít lỗi nhất
        return min(available, key=lambda p: (p.failures, p.last_used))

    def rotate(self) -> Optional[ProxyInfo]:
        """Xoay sang proxy tiếp theo"""
        if not self.enabled or not self.proxies:
            return None

        available = [p for p in self.proxies if p.is_available]
        if not available:
            return None

        # Round-robin với random
        random.shuffle(available)
        chosen = available[0]
        logger.info(f"Rotated to proxy: {chosen.proxy_id} | {chosen.server[:30]}...")
        return chosen

    def mark_dead(self, proxy: ProxyInfo):
        proxy.is_dead = True
        logger.warning(f"Proxy {proxy.proxy_id} marked dead")

    @property
    def stats(self) -> Dict:
        return {
            "total": len(self.proxies),
            "available": sum(1 for p in self.proxies if p.is_available),
            "dead": sum(1 for p in self.proxies if p.is_dead),
        }
