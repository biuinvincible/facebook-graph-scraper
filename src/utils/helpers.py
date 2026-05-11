"""
Utility helpers: delays, text cleaning, URL parsing, emoji extraction.
"""
import asyncio
import random
import re
import unicodedata
from typing import List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from loguru import logger


# ─── DELAY HELPERS ──────────────────────────────────────────────────────────

async def human_delay(min_s: float = 1.0, max_s: float = 3.5):
    """Random delay to simulate human behavior"""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


async def micro_delay():
    await asyncio.sleep(random.uniform(0.1, 0.5))


async def human_scroll(page, steps: int = 3, pause_min: float = 0.8, pause_max: float = 2.0):
    """Scroll page with human-like random pauses"""
    for _ in range(steps):
        scroll_amount = random.randint(300, 800)
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await asyncio.sleep(random.uniform(pause_min, pause_max))


# ─── URL HELPERS ─────────────────────────────────────────────────────────────

def normalize_fb_url(url: str) -> str:
    """Normalize Facebook URL, remove tracking params"""
    if not url:
        return url
    try:
        parsed = urlparse(url)
        # Keep only essential query params
        keep_params = {"id", "story_fbid", "v", "fbid"}
        qs = parse_qs(parsed.query)
        clean_qs = {k: v for k, v in qs.items() if k in keep_params}
        clean_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, urlencode(clean_qs, doseq=True), ""
        ))
        return clean_url
    except Exception:
        return url


def extract_post_id(url: str) -> Optional[str]:
    """Extract post ID from various Facebook URL formats"""
    if not url:
        return None

    # /posts/1234567890
    m = re.search(r"/posts/(\d+)", url)
    if m:
        return m.group(1)

    # /permalink/1234567890
    m = re.search(r"/permalink/(\d+)", url)
    if m:
        return m.group(1)

    # story_fbid=1234567890
    m = re.search(r"story_fbid=(\d+)", url)
    if m:
        return m.group(1)

    # /p/XXXXX (reels, new format)
    m = re.search(r"/p/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    # /reel/1234567890
    m = re.search(r"/reel/(\d+)", url)
    if m:
        return m.group(1)

    # ?v=1234567890 (video)
    m = re.search(r"[?&]v=(\d+)", url)
    if m:
        return m.group(1)

    # pfbid (newer encoded IDs)
    m = re.search(r"pfbid([A-Za-z0-9]+)", url)
    if m:
        return "pfbid" + m.group(1)

    # photo/?fbid=1234 or /photo/1234
    m = re.search(r"[?&]fbid=(\d+)", url)
    if m:
        return m.group(1)

    m = re.search(r"/photo/(\d+)", url)
    if m:
        return m.group(1)

    return None


def extract_user_id(url: str) -> Optional[str]:
    """Extract user/page ID from Facebook profile URL"""
    if not url:
        return None

    # ?id=1234567890
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)

    # /profile.php?id=
    m = re.search(r"profile\.php\?id=(\d+)", url)
    if m:
        return m.group(1)

    # username in path
    m = re.match(r"https?://(?:www\.)?facebook\.com/([^/?#]+)", url)
    if m:
        slug = m.group(1)
        if slug not in ("pages", "groups", "events", "marketplace", "watch"):
            return slug

    return None


# ─── TEXT CLEANING ────────────────────────────────────────────────────────────

EMOJI_PATTERN = re.compile(
    "[\U00010000-\U0010FFFF"
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251]+",
    flags=re.UNICODE,
)

HASHTAG_PATTERN = re.compile(r"#(\w+)", re.UNICODE)
MENTION_PATTERN = re.compile(r"@([\w.]+)", re.UNICODE)
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")


def extract_hashtags(text: str) -> List[str]:
    if not text:
        return []
    return list(set(HASHTAG_PATTERN.findall(text)))


def extract_mentions(text: str) -> List[str]:
    if not text:
        return []
    return list(set(MENTION_PATTERN.findall(text)))


def extract_emojis(text: str) -> List[str]:
    if not text:
        return []
    return EMOJI_PATTERN.findall(text)


def extract_external_links(text: str) -> List[str]:
    if not text:
        return []
    return URL_PATTERN.findall(text)


def clean_text(text: str) -> str:
    """Basic text normalization (keep original in raw_text)"""
    if not text:
        return text
    # Normalize unicode (NFC)
    text = unicodedata.normalize("NFC", text)
    # Remove zero-width chars
    text = re.sub(r"[​‌‍﻿]", "", text)
    # Collapse multiple whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_count(text: str) -> int:
    """Parse Facebook engagement counts like '1.2K', '3M', '1,234'"""
    if not text:
        return 0
    text = text.strip().replace(",", "").replace(".", "")
    text_lower = text.lower()
    try:
        if text_lower.endswith("k"):
            return int(float(text_lower[:-1]) * 1000)
        if text_lower.endswith("m"):
            return int(float(text_lower[:-1]) * 1_000_000)
        if text_lower.endswith("b"):
            return int(float(text_lower[:-1]) * 1_000_000_000)
        # Handle "1.2K" style with dot
        if re.match(r"^\d+$", text):
            return int(text)
        return 0
    except (ValueError, TypeError):
        return 0


def parse_reaction_text(text: str) -> Tuple[int, str]:
    """Parse '1,234 Thích' -> (1234, 'like')"""
    REACTION_MAP = {
        "thích": "like", "like": "like",
        "yêu": "love", "love": "love",
        "haha": "haha",
        "wow": "wow",
        "buồn": "sad", "sad": "sad",
        "phẫn nộ": "angry", "angry": "angry",
        "thương thương": "care", "care": "care",
    }
    text_lower = text.lower()
    for keyword, reaction in REACTION_MAP.items():
        if keyword in text_lower:
            count_match = re.search(r"[\d,\.]+[kKmMbB]?", text)
            count = parse_count(count_match.group(0)) if count_match else 0
            return count, reaction
    return 0, "unknown"
