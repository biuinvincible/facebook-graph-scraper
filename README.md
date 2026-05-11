# Facebook Graph Scraper

Autonomous Facebook public content crawler for building **Heterogeneous Graph (HetG)** training datasets for multimodal GNN models (e.g. Graph Embedding cho mạng xã hội Việt Nam).

## Features

- **Autonomous crawling** — Pages, Groups, Search, Hashtags, Single Posts
- **Full comment tree** — Top-level comments + all nested replies  
- **Multimodal** — Text, images, videos, OCR (Vietnamese + English)
- **Graph structure** — Nodes (User, Post, Comment) + Edges (User-Post, User-User, Post-Post)
- **Anti-detection** — Stealth browser, randomized delays, UA rotation, Vietnamese locale
- **Dual storage** — SQLite (relational queries) + JSON (ML training)
- **Session persistence** — Cookie reuse across runs

## Data Schema (GNN-ready)

Each scraped post becomes a `GraphSample` with:

```json
{
  "sample_id": "vngraph_001",
  "post_id": "...",
  "post_url": "https://www.facebook.com/...",

  "node_features": {
    "text": "Món này đỉnh của chóp luôn! #foodreview #saigon",
    "cleaned_text": "...",
    "hashtags": ["foodreview", "saigon"],
    "mentions": [],
    "emojis": ["😍"],
    "language": "vi",
    "image_urls": ["https://..."],
    "ocr_results": [{"text": "Giảm 50%", "confidence": 87.2, "image_idx": 0}]
  },

  "engagement": {
    "like": 1234, "love": 567, "haha": 89,
    "wow": 12, "sad": 3, "angry": 1, "care": 45,
    "comment_count": 234, "share_count": 89
  },

  "graph_structure": {
    "author_id": "user_123",
    "author_name": "Nguyễn Văn A",
    "neighbors": [
      {"user_id": "user_456", "type": "comment", "content": "Địa chỉ ở đâu?", "timestamp": "..."},
      {"user_id": "user_789", "type": "share", "timestamp": "..."}
    ],
    "comment_tree": [
      {
        "comment_id": "...", "author_id": "...", "raw_text": "...",
        "replies": [...]
      }
    ]
  },

  "metadata": {
    "timestamp": "2026-05-07T...",
    "location": "Ho Chi Minh City",
    "source_page": "https://...",
    "scraped_at": "2026-05-07T..."
  }
}
```

## Graph Node/Edge Types

| Type | Fields |
|------|--------|
| **User Node** | user_id, display_name, bio_text, profile_image_url, follower_count, is_verified |
| **Post Node** | post_id, raw_text, hashtags, image_urls, ocr_results, engagement counts |
| **Comment Node** | comment_id, parent_id (tree), depth, author_id, raw_text, like_count |
| **User→Post Edge** | interaction_type (like/love/haha/wow/sad/angry/care/comment/share), weight |
| **User→User Edge** | relation_type (follow/friend/mention/tag) |
| **Post→Post Edge** | similarity_type (hashtag/topic), shared_hashtags, similarity_score |

## Setup

```bash
# Install
chmod +x setup.sh && ./setup.sh

# Or manually:
pip install -r requirements.txt
playwright install chromium
# For OCR: sudo apt-get install tesseract-ocr tesseract-ocr-vie
```

## Usage

```bash
# 1. Login (saves cookies for future runs)
python main.py login --email your@email.com

# 2. Scrape a public page
python main.py scrape --target page --url https://www.facebook.com/vnexpress.net

# 3. Scrape a public group
python main.py scrape --target group --url https://www.facebook.com/groups/amthucvietnam

# 4. Search by keyword
python main.py scrape --target search --query "ẩm thực sài gòn" --max-posts 200

# 5. Scrape a hashtag
python main.py scrape --target hashtag --query foodreview --max-posts 150

# 6. Multi-target from file
python main.py scrape --from-file targets_example.yaml

# 7. Check stats
python main.py stats
```

## Project Structure

```
facebook-craper/
├── src/
│   ├── crawler.py              # Main orchestrator
│   ├── scrapers/
│   │   ├── base.py             # Login, navigation, scrolling
│   │   ├── page_scraper.py     # Page/Profile scraper
│   │   ├── group_scraper.py    # Group scraper
│   │   └── search_scraper.py   # Search/Hashtag scraper
│   ├── extractors/
│   │   ├── post_extractor.py   # Post data extraction
│   │   ├── comment_extractor.py # Comment tree extraction
│   │   ├── media_extractor.py  # Image/video download + OCR
│   │   └── user_extractor.py   # User profile extraction
│   ├── graph/
│   │   ├── schema.py           # Node/Edge dataclasses
│   │   └── edge_builder.py     # Post-Post similarity edges
│   └── storage/
│       ├── database.py         # SQLite async storage
│       └── json_storage.py     # JSON file storage
├── data/
│   ├── json/                   # Per-post JSON files (GNN training)
│   ├── media/                  # Downloaded images/videos
│   └── facebook_graph.db       # SQLite graph database
├── cookies/                    # Saved browser sessions
├── config.yaml                 # Main configuration
├── targets_example.yaml        # Example scraping targets
├── main.py                     # CLI entry point
└── requirements.txt
```

## Configuration

Edit `config.yaml` to control:
- `scraper.headless` — visible or headless browser
- `scraping.max_posts_per_target` — how many posts per target
- `scraping.max_comments` — max comments per post
- `storage.download_media` — download images/videos
- `ocr.enabled` — run OCR on images

## Tips for Vietnamese Content

1. **Locale is pre-set** to `vi-VN` and timezone `Asia/Ho_Chi_Minh`
2. **OCR** uses `vie+eng` language pack for Vietnamese text in memes
3. **"Thương thương"** (Care reaction) is tracked separately as it's common on Vietnamese FB
4. **Teencode** raw text is preserved in `raw_text`; normalize separately with ViSoBERT preprocessing

## Legal Notice

This tool is for **academic research only**. Always comply with:
- Facebook's Terms of Service
- Local data protection laws (PDPA Vietnam)
- Only scrape public content
- Do not store personal data beyond research needs
