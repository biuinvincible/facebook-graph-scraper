# Facebook Graph Scraper

Autonomous Facebook public content crawler for building **Heterogeneous Graph Neural Network (HetGNN)** training datasets from Vietnamese social media.

Scrapes posts, full comment trees, user interaction edges, and media — then exports each post as a `GraphSample` JSON ready to load into PyTorch Geometric `HeteroData`.

---

## Architecture

```
Facebook (public pages/groups/search)
        |
        v
  Playwright browser (stealth, Vietnamese locale)
        |
    page_scraper / group_scraper / search_scraper
        |
    post_extractor  comment_extractor  media_extractor  user_extractor
        |                  |                 |
        +------------------+-----------------+
        |
    GraphSample (schema.py)  <-- edge_builder adds Post-Post edges
        |
        +-----------> data/raw/{post_id}.json   (ML training)
        +-----------> data/facebook_graph.db    (SQLite, relational)
        +-----------> data/media/{post_id}/     (downloaded images)
        |
        v
  src/graph/to_pyg.py
        |
        v
  PyTorch Geometric HeteroData
        |
        v
  GNN training (ViSoBERT + Graph Transformer / HGT)
```

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ | Required |
| Playwright / Chromium | latest | Headless browser |
| Tesseract OCR | any | For image text extraction |
| Vietnamese Tesseract pack | any | `tesseract-ocr-vie` |
| Facebook account cookies | — | Clone/research account |

---

## Installation

```bash
# 1. Clone and enter project
git clone <repo-url>
cd facebook-scraper

# 2. Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Chromium browser
playwright install chromium

# 5. Install Tesseract (Ubuntu/Debian)
sudo apt-get install tesseract-ocr tesseract-ocr-vie

# 6. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your Facebook clone-account credentials
```

---

## Quick Start

### Step 1 — Login and save session cookies

```bash
python main.py login --email your@email.com
# Prompted for password. Saves cookies/session.json for future runs.
```

### Step 2 — Collect post URLs from a page

```bash
# Single page (outputs targets.yaml)
python collect_urls.py https://www.facebook.com/SomePage/ targets.yaml 500

# Parallel (multiple pages at once using pages_config.yaml)
python collect_urls.py --parallel pages_config.yaml targets.yaml
```

`pages_config.yaml` format:
```yaml
- url: https://www.facebook.com/PageWSS/
  session: cookies/session_2.json
  category: hai_meme
  max_posts: 1500
- url: https://www.facebook.com/trollbongda/
  session: cookies/session_3.json
  category: the_thao
  max_posts: 1500
```

### Step 3 — Scrape posts

```bash
# From a targets file
python main.py scrape --from-file targets.yaml

# Single page
python main.py scrape --target page --url https://www.facebook.com/vnexpress.net

# Single group
python main.py scrape --target group --url https://www.facebook.com/groups/amthucvietnam

# Search by keyword
python main.py scrape --target search --query "ẩm thực sài gòn" --max-posts 200

# Hashtag
python main.py scrape --target hashtag --query foodreview --max-posts 150

# Single post
python main.py scrape --target post --url https://www.facebook.com/permalink.php?story_fbid=XXX&id=YYY
```

### Step 4 — Check progress

```bash
python scrape_status.py
python main.py stats
```

---

## Parallel Scraping (recommended for large datasets)

Runs N workers in parallel — each worker uses a separate session cookie and writes to its own SQLite DB to avoid lock contention.

```bash
# 5 workers, default targets_all_domains.yaml
python parallel_scrape.py targets_all_domains.yaml 5

# Custom worker count
python parallel_scrape.py my_targets.yaml 3
```

Each worker:
- Gets its own chunk of the target list
- Uses `cookies/session_{N}.json`
- Writes to `data/worker_{N}.db` and `data/checkpoint_{N}.json`
- Logs to `logs/worker_{N}.log`

After all workers finish, DBs are automatically merged:
```bash
python merge_dbs.py   # merges worker_*.db → data/facebook_graph.db
```

---

## File Structure

```
facebook-scraper/
├── src/
│   ├── crawler.py                  # Main orchestrator (ban recovery, session rotation)
│   ├── scrapers/
│   │   ├── base.py                 # Login, navigation, ban detection, rate limiting
│   │   ├── page_scraper.py         # Facebook Pages and public profiles
│   │   ├── group_scraper.py        # Public Facebook Groups
│   │   └── search_scraper.py       # Keyword search and hashtag feeds
│   ├── extractors/
│   │   ├── post_extractor.py       # Post text, reactions, metadata
│   │   ├── comment_extractor.py    # Full comment tree (nested replies)
│   │   ├── media_extractor.py      # Image/video download + OCR
│   │   └── user_extractor.py       # User profile information
│   ├── graph/
│   │   ├── schema.py               # Node/Edge dataclasses (PostNode, UserNode, etc.)
│   │   ├── edge_builder.py         # Builds Post-Post hashtag-similarity edges
│   │   └── to_pyg.py               # JSON → PyTorch Geometric HeteroData converter
│   ├── storage/
│   │   ├── database.py             # Async SQLite backend (aiosqlite)
│   │   └── json_storage.py         # Atomic JSON file writer per post
│   └── utils/
│       ├── browser.py              # Playwright stealth browser manager
│       ├── ban_detector.py         # Detects checkpoints, rate limits, bans
│       ├── session_manager.py      # Multi-account rotation
│       ├── checkpoint.py           # Resume-after-crash (atomic writes)
│       ├── rate_limiter.py         # Adaptive exponential backoff
│       ├── proxy_manager.py        # Optional proxy rotation
│       └── helpers.py              # Utilities (extract_post_id, human_delay, etc.)
│
├── main.py                         # CLI: scrape / login / stats / validate_targets
├── parallel_scrape.py              # Multi-worker orchestrator
├── collect_urls.py                 # URL collector (single + parallel modes)
├── scrape_status.py                # Live progress display
├── merge_dbs.py                    # Merge worker DBs after parallel run
│
├── config.yaml                     # Main scraper configuration
├── targets_example.yaml            # Example targets file (3 entries)
├── targets_all_domains.yaml        # Full dataset: 13,790 URLs across 9 categories
│
├── cookies/                        # Browser session cookies (gitignored)
│   └── session.json                # Default session; session_2.json … session_6.json
├── data/
│   ├── raw/                        # Per-post JSON files (GNN training input)
│   ├── media/                      # Downloaded images
│   ├── checkpoint.json             # Resume state
│   └── facebook_graph.db           # Merged SQLite graph database
├── logs/                           # Per-worker log files
└── tests/                          # 813 tests, ~91% coverage
```

---

## Configuration Reference

Key settings in `config.yaml`:

```yaml
scraper:
  headless: true           # false = visible browser window (for debugging)
  slow_mo: 0               # ms added between Playwright actions
  timeout: 30000           # page navigation timeout (ms)
  stealth: true            # enable anti-detection fingerprinting
  randomize_delays: true   # randomize wait times between requests
  min_delay: 1.5           # minimum seconds between requests
  max_delay: 4.0
  cookies_file: "cookies/session_2.json"

storage:
  output_dir: "data/raw"   # JSON output directory
  media_dir: "data/media"
  db_path: "data/facebook_graph.db"
  download_media: true
  max_media_size_mb: 50

scraping:
  max_comments: 200        # max comments to fetch per post
  max_replies_per_comment: 50
  max_posts_per_target: 200
  post_timeout_seconds: 600  # kill a stalled post after 10 min

ocr:
  enabled: true
  lang: "vie+eng"          # Tesseract language pack

protection:
  checkpoint_file: "data/checkpoint.json"
  checkpoint_flush_every: 5    # write to disk every 5 posts
  sessions_dir: "cookies"      # directory with session_*.json files
  max_retries_per_target: 3
  backoff_base_seconds: 60     # 60s → 120s → 240s exponential backoff
```

---

## Data Format

Each scraped post is saved as `data/raw/{post_id}.json`:

```json
{
  "sample_id": "vngraph_a1b2c3d4",
  "post_id": "123456789012345",
  "post_url": "https://www.facebook.com/SomePage/posts/123456789012345",
  "platform": "facebook",

  "node_features": {
    "text": "Món này đỉnh của chóp luôn! #foodreview #saigon",
    "cleaned_text": "Món này đỉnh của chóp luôn!",
    "hashtags": ["foodreview", "saigon"],
    "mentions": [],
    "emojis": ["😍"],
    "language": "vi",
    "image_urls": ["https://cdn.facebook.com/..."],
    "local_images": ["data/media/123456789012345/img_0.jpg"],
    "ocr_results": [{"text": "Giảm 50%", "confidence": 87.2, "image_idx": 0}]
  },

  "engagement": {
    "like": 1234, "love": 567, "haha": 89,
    "wow": 12, "sad": 3, "angry": 1, "care": 45,
    "comment_count": 234, "share_count": 89,
    "total_reactions": 1951
  },

  "graph_structure": {
    "author_id": "user_abc123",
    "author_name": "Nguyễn Văn A",
    "comment_tree": [
      {
        "comment_id": "cmt_001", "author_id": "user_xyz", "depth": 0,
        "raw_text": "Địa chỉ ở đâu vậy bạn?", "like_count": 12,
        "replies": [
          {"comment_id": "cmt_002", "depth": 1, "raw_text": "123 Nguyễn Huệ nè", ...}
        ]
      }
    ],
    "hashtag_nodes": [{"hashtag": "foodreview", "frequency": 1}],
    "edges_user_post": [
      {"user_id": "user_abc123", "post_id": "...", "interaction_type": "author", "weight": 10.0}
    ],
    "edges_user_comment": [...],
    "edges_user_user": [...],
    "edges_comment_reply": [...],
    "edges_post_hashtag": [...]
  },

  "metadata": {
    "timestamp": "2026-05-07T14:23:00",
    "location": "Ho Chi Minh City",
    "post_type": "post",
    "source_page": "https://www.facebook.com/SomePage/",
    "scraped_at": "2026-05-07T14:30:00"
  }
}
```

### Load as PyTorch Geometric HeteroData

```python
from src.graph.to_pyg import to_pyg_heterodata

data = to_pyg_heterodata("data/raw/123456789012345.json")
# data['post'].x           → (1, 1)  placeholder — replace with text embeddings
# data['user'].x           → (N, 1)
# data['comment'].x        → (M, 1)
# data['post'].engagement  → (1, 10) [like, love, haha, wow, sad, angry, care, comments, shares, total]
# data['user', 'author', 'post'].edge_index    → (2, E)
# data['comment', 'reply_to', 'post'].edge_index → (2, E)
# etc.

# If PyG not available, use the dict form:
from src.graph.to_pyg import json_to_hetero_dict
d = json_to_hetero_dict("data/raw/123456789012345.json")
# d['num_nodes']  → {'post': 1, 'user': N, 'comment': M, 'hashtag': H}
# d['edge_index'] → {('user','author','post'): np.array shape (2,E), ...}
```

---

## Graph Schema

### Node Types

| Node | Key Fields |
|---|---|
| `Post` | post_id, raw_text, cleaned_text, hashtags, mentions, emojis, language, image_urls, ocr_results, like/love/haha/wow/sad/angry/care counts, comment_count, share_count |
| `User` | user_id, display_name, bio_text, profile_image_url, follower_count, is_verified, is_page |
| `Comment` | comment_id, parent_id (None = top-level), depth (0/1/2+), raw_text, like_count, author_id |
| `Hashtag` | hashtag (text), frequency, post_ids |

### Edge Types

| Edge | Direction | Relation | Notes |
|---|---|---|---|
| `UserPostEdge` | User → Post | author, comment, share, like, love, haha, wow, sad, angry, care | Weighted (author=10, share=5, comment=3, reactions=1–2) |
| `UserCommentEdge` | User → Comment | author | Comment authorship |
| `UserUserEdge` | User ↔ User | reply, reply_rev, mention, mention_rev | From comment interactions |
| `CommentReplyEdge` | Comment → Post/Comment | reply_to, reply_to_rev | Conversation tree structure |
| `PostHashtagEdge` | Post ↔ Hashtag | has_hashtag, in_post | Bidirectional |
| `PostPostEdge` | Post ↔ Post | hashtag (Jaccard overlap) | Built by EdgeBuilder after scraping |

---

## Dataset: `targets_all_domains.yaml`

13,790 post URLs across 9 Vietnamese content categories:

| Category | Posts | Description |
|---|---|---|
| `the_thao` | 5,025 | Football, sports commentary |
| `hai_meme` | 3,712 | Humor, memes |
| `confession` | 2,000 | Anonymous confessions |
| `am_nhac` | 1,696 | Music, entertainment |
| `giai_tri` | 1,004 | General entertainment |
| `am_thuc` | 162 | Food and restaurants |
| `tin_tuc` | 96 | News |
| `lifestyle` | 70 | Lifestyle content |
| `cong_nghe` | 25 | Technology |

---

## Adding New Target Pages

1. Create a pages config file (e.g., `pages_new.yaml`):

```yaml
- url: https://www.facebook.com/NewPage/
  session: cookies/session_2.json
  category: my_category
  max_posts: 1000
```

2. Collect post URLs:

```bash
python collect_urls.py --parallel pages_new.yaml targets_new.yaml
```

3. Scrape the collected URLs:

```bash
python parallel_scrape.py targets_new.yaml 4
```

4. Check results:

```bash
python scrape_status.py
python main.py stats
```

---

## Running Tests

```bash
.venv/bin/pytest tests/ --cov=src -q
```

813 tests, ~91% line coverage.

---

## Legal Notice

This tool is for **academic research only**. You are responsible for:
- Complying with Facebook's Terms of Service
- Complying with Vietnamese data protection law (PDPA)
- Only scraping publicly accessible content
- Not storing personal data beyond legitimate research needs
- Obtaining ethical approval if required by your institution
