# Facebook Graph Scraper

Thu thập posts, comment trees và interaction edges từ Facebook public pages — xuất ra JSON sẵn dùng cho GNN training.

---

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # điền FB_EMAIL, FB_PASSWORD
```

### Login (lần đầu)

```bash
python login.py cookies/session_2.json
# Làm theo hướng dẫn trên màn hình, lặp lại cho session_3.json ... session_6.json
```

---

## Workflow

### 1. Thu thập URLs từ một page

```bash
# Single page
python collect_urls.py https://www.facebook.com/PageWSS/ targets.yaml 2000

# Parallel (nhiều pages cùng lúc)
python collect_urls.py --parallel pages_config.yaml targets_all.yaml
```

**Format `pages_config.yaml`:**
```yaml
- url: https://www.facebook.com/neuconfessions/
  session: cookies/session_2.json
  category: confession
  max_posts: 2000
- url: https://www.facebook.com/trollbongda/
  session: cookies/session_3.json
  category: the_thao
  max_posts: 2000
```

### 2. Scrape (parallel, 3–4 workers)

```bash
# Detach khỏi terminal để không bị lag
nohup python parallel_scrape.py targets_all.yaml 4 > logs/orchestrator.log 2>&1 & disown
```

### 3. Check tiến độ

```bash
python scrape_status.py
```

### 4. Scrape single post (test)

```bash
python main.py scrape --from-file targets_example.yaml
```

---

## Data

Mỗi post được lưu tại `data/raw/{post_id}.json`:

```
data/
  raw/          ← {post_id}.json (text, engagement, graph edges)
  media/        ← {post_id}/img_000.jpg (ảnh post)
```

**Cấu trúc JSON:**
```json
{
  "post_id": "...",
  "node_features": { "text": "...", "image_urls": [...] },
  "engagement": { "like": 0, "comment_count": 0, ... },
  "graph_structure": {
    "comment_tree": [...],
    "edges_user_user": [...],
    "edges_comment_reply": [...]
  }
}
```

**Edge types có trong data:**

| Edge | Ý nghĩa |
|---|---|
| `(user) --[author]--> (post)` | Tác giả bài đăng |
| `(user) --[author]--> (comment)` | Tác giả bình luận |
| `(comment) --[reply_to]--> (post/comment)` | Cây hội thoại |
| `(user) --[reply]--> (user)` | Ai trả lời ai |
| `(user) --[mention]--> (user)` | Ai tag ai |
| `(post) --[has_hashtag]--> (hashtag)` | Hashtag |

---

## Load vào PyG

```python
from src.graph.to_pyg import json_to_hetero_dict

data = json_to_hetero_dict("data/raw/some_post.json")
# data["num_nodes"], data["edge_index"], data["post_engagement"]
```

---

## Config

Chỉnh `config.yaml`:

```yaml
scraper:
  headless: true       # false để debug
  max_comments: 200    # giới hạn comments/post
  post_timeout_seconds: 600
```

---

## Tests

```bash
.venv/bin/pytest tests/ -q
```
