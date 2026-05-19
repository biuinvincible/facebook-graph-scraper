# CLAUDE.md — AI Assistant Guide

This file helps AI assistants understand this codebase quickly.

---

## Codebase Map

### Entry Points

| File | Purpose |
|---|---|
| `main.py` | CLI via Click: `scrape`, `login`, `stats`, `validate_targets` |
| `parallel_scrape.py` | Splits targets into N chunks, spawns N `main.py` subprocesses |
| `collect_urls.py` | Scrolls Facebook pages to collect post URLs into a YAML targets file |
| `scrape_status.py` | Quick progress display: reads checkpoint JSONs and log files |
| `merge_dbs.py` | Merges `data/worker_{N}.db` files into `data/facebook_graph.db` |
| `login.py` | Standalone interactive login (separate from main.py login command) |

### Core Pipeline: `src/`

```
crawler.py               — Top-level orchestrator
  └─ scrapers/
       base.py           — Login, navigation, ban detection, rate limiter
       page_scraper.py   — Scrolls a Facebook Page/profile, calls extractors per post
       group_scraper.py  — Same but for Groups
       search_scraper.py — Keyword search and hashtag feeds
  └─ extractors/
       post_extractor.py     — Parses DOM for post text, reactions, timestamp, author
       comment_extractor.py  — Recursively loads "View more replies" to build full tree
       media_extractor.py    — Downloads images, runs Tesseract OCR (vie+eng)
       user_extractor.py     — Scrapes author profile (optional, slow)
  └─ graph/
       schema.py         — All dataclasses: PostNode, UserNode, CommentNode,
                           UserPostEdge, UserUserEdge, UserCommentEdge,
                           CommentReplyEdge, PostHashtagEdge, PostPostEdge,
                           HashtagNode, GraphSample
       edge_builder.py   — Builds Post→Post edges by Jaccard hashtag overlap
       to_pyg.py         — JSON file → PyG HeteroData (or numpy dict without PyG)
  └─ storage/
       database.py       — Async SQLite via aiosqlite; CREATE TABLE + upsert methods
       json_storage.py   — Writes GraphSample → data/raw/{post_id}.json atomically
  └─ utils/
       browser.py        — BrowserManager: stealth Chromium, UA rotation, cookie load/save
       ban_detector.py   — Reads page text/URL for 7 ban signatures (checkpoint, rate_limit, etc.)
       session_manager.py — Rotates among cookies/session_{N}.json when one gets banned
       checkpoint.py     — ScrapingCheckpoint: tracks scraped_ids, flushes every N posts
       rate_limiter.py   — AdaptiveRateLimiter: exponential backoff, auto-recovery
       proxy_manager.py  — Optional proxy rotation (disabled by default)
       helpers.py        — extract_post_id(), extract_mentions(), human_delay(), micro_delay()
```

### Data Flow (single post)

1. `PageScraper.scrape_page()` navigates to the page URL
2. Scrolls feed, calls `PostExtractor.extract()` per visible post
3. `CommentExtractor.extract_comments()` expands "View more" until `max_comments`
4. `MediaExtractor.download_post_media()` downloads images, runs OCR
5. `UserExtractor.extract_user()` optionally fetches author profile
6. Assembles a `GraphSample` with nodes + edges
7. `JsonStorage.save_sample()` writes `data/raw/{post_id}.json` atomically
8. `Database.save_graph_sample()` writes rows to SQLite

---

## Key Design Decisions

### Why Heterogeneous Graph (HetG) over homogeneous?

Different node types (Post, User, Comment, Hashtag) have semantically different features and roles. A homogeneous graph would force all nodes into the same feature space. PyG `HeteroData` with type-specific encoders (e.g., ViSoBERT for text nodes, engagement vector for Post) preserves this distinction and allows message-passing along typed edges (e.g., `user --author--> post` vs `user --reply--> user`).

### Why `domcontentloaded` instead of `networkidle`?

Facebook's feed is infinite-scroll with deferred asset loading — `networkidle` never fires reliably and times out. `domcontentloaded` triggers as soon as the initial DOM is parsed; the scraper then manually waits (`asyncio.sleep`) and uses JS-evaluated scroll events to detect when new content is rendered.

### Why atomic writes for cookies and checkpoints?

Both the checkpoint file and session cookies are written via a `tmp → rename` pattern:

```python
# checkpoint.py
tmp = self.checkpoint_file.with_suffix(".tmp")
with open(tmp, "w") as f:
    json.dump(data, f)
tmp.replace(self.checkpoint_file)   # atomic on POSIX
```

```python
# json_storage.py
tmp_path = filepath.with_suffix(".tmp")
async with aiofiles.open(tmp_path, "wb") as f:
    await f.write(orjson.dumps(data, ...))
tmp_path.replace(filepath)
```

This prevents a half-written file if the process is killed mid-write (ban, crash, OOM). A reader will always see either the old complete file or the new complete file — never a partial one.

### Why separate SQLite DBs per worker?

SQLite with WAL mode can handle concurrent readers but only one writer at a time. With 5 parallel workers each writing hundreds of rows per minute, a shared DB creates lock contention that stalls workers. Each worker gets `data/worker_{N}.db`; `merge_dbs.py` does a one-time `INSERT OR IGNORE` merge after all workers finish.

### Why `INSERT OR IGNORE` for deduplication?

Post IDs are deterministic (extracted from the Facebook URL). If two workers independently collect the same post (edge case when targets overlap), the second insert is silently dropped. This is simpler and faster than a pre-scrape dedup check.

### Edge weights

`UserPostEdge.WEIGHTS`:
```python
{"author": 10.0, "share": 5.0, "comment": 3.0,
 "love": 2.0, "care": 2.0, "wow": 1.5, "haha": 1.5,
 "sad": 1.5, "angry": 1.5, "like": 1.0}
```
These encode engagement intensity for GNN edge weighting. Author is highest because content creation is the strongest signal.

---

## Common Debugging Patterns

### Session expired / redirects to login

```bash
# Re-login and save new cookies
python main.py login --email your@email.com

# Or for a specific session slot
COOKIES_OVERRIDE=cookies/session_3.json python collect_urls.py <url>
```

### Worker stuck / not progressing

```bash
# Check which worker is stalled
python scrape_status.py

# Tail a specific worker log
tail -f logs/worker_2.log

# Kill and restart just that worker (checkpoint will resume from last saved point)
```

### "Ban detected" — checkpoint triggered

The scraper auto-rotates to the next available session. Check `logs/orchestrator.log` for `Session X BANNED` messages. If all sessions are banned, wait ~24h and re-run.

### SQLite "database is locked"

Ensure you are not running `python main.py stats` (which opens the main DB) while `merge_dbs.py` is writing. The merge script uses `PRAGMA journal_mode=WAL` but a stats read during merge can still contend.

### OCR returns garbage

- Ensure `tesseract-ocr-vie` is installed: `tesseract --list-langs | grep vie`
- Check `ocr.confidence_threshold: 60` in config.yaml — raise to 75 to filter low-quality results
- OCR is only run on images in posts, not profile pictures

### Post text is empty

`post_extractor.py` targets specific CSS selectors that Facebook A/B tests. If text extraction fails for a batch of posts, inspect one URL manually in a non-headless browser (`headless: false` in config.yaml) and update the selectors in `PostExtractor._extract_text()`.

---

## Test Running

```bash
# Full test suite with coverage
.venv/bin/pytest tests/ --cov=src -q

# Single test file
.venv/bin/pytest tests/test_post_extractor.py -v

# Run only fast unit tests (skip browser/async tests)
.venv/bin/pytest tests/ -m "not slow" -q

# Coverage report in HTML
.venv/bin/pytest tests/ --cov=src --cov-report=html -q
# Open htmlcov/index.html
```

Test files map to source modules:

| Test file | Covers |
|---|---|
| `test_post_extractor.py`, `test_post_extractor_photo*.py` | `extractors/post_extractor.py` |
| `test_comment_extractor*.py` | `extractors/comment_extractor.py` |
| `test_media_extractor*.py` | `extractors/media_extractor.py` |
| `test_schema.py` | `graph/schema.py` |
| `test_edge_builder.py` | `graph/edge_builder.py` |
| `test_database.py` | `storage/database.py` |
| `test_json_storage.py` | `storage/json_storage.py` |
| `test_checkpoint.py` | `utils/checkpoint.py` |
| `test_browser.py` | `utils/browser.py` |
| `test_ban_detector.py` | `utils/ban_detector.py` |
| `test_session_manager.py` | `utils/session_manager.py` |
| `test_crawler*.py` | `crawler.py` |
| `test_base_scraper.py`, `test_page_scraper.py` | `scrapers/` |

---

## Environment Variables

Loaded automatically from `.env` via `python-dotenv`:

| Variable | Used in | Purpose |
|---|---|---|
| `FB_EMAIL` | `main.py login`, `scrape` command | Facebook login email |
| `FB_PASSWORD` | `main.py login`, `scrape` command | Facebook login password |
| `PROXY_SERVER` | `config.yaml` proxy section | Optional proxy URL |
| `COOKIES_OVERRIDE` | `collect_urls.py` single mode | Override default session file path |
