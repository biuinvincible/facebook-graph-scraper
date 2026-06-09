# Facebook Graph Scraper

Thu thập posts, comment trees và interaction edges từ Facebook public pages — xuất ra JSON sẵn dùng cho GNN training.

**Node types:** Post, User, Comment, Hashtag, Image  
**Edge types:** author, reply_to, mention, has_hashtag, share

---

## Setup (Ubuntu / Debian / WSL2)

```bash
git clone <repo>
cd facebook-scraper
bash setup.sh
```

`setup.sh` tự động:
- Kiểm tra Python 3.10+
- Cài system packages (tesseract, playwright deps, screen)
- Tạo `.venv` và `pip install -r requirements.txt`
- Cài Playwright Chromium
- Tạo `.env` từ template

### Login (bắt buộc trước khi crawl)

Cần ít nhất **3 session files** để có thể rotate khi bị ban:

```bash
python login.py cookies/session_2.json
python login.py cookies/session_3.json
python login.py cookies/session_4.json
# Optional: session_5.json, session_6.json
```

Làm theo hướng dẫn trên màn hình (nhập email/password, xác nhận 2FA nếu có).

---

## Workflow

### 1. Thu thập URLs

```bash
# Auto-restart khi crash (khuyên dùng)
bash monitor_collect.sh       # chạy game2 + batch8, tự restart nếu crash

# Chạy thủ công từng batch
bash collect_urls.sh          # tất cả 8 batches
bash collect_urls.sh 3        # từ batch 3 đến 8
bash collect_urls.sh 3 5      # chỉ batch 3, 4, 5

# Theo dõi
bash status_collect.sh

# Dừng
bash stop_collect.sh
```

Kết quả lưu vào `targets_all_domains.yaml` — 40 pages, 10 categories:  
`tin_tuc`, `the_thao`, `hai_meme`, `cong_nghe`, `kinh_te`, `giao_duc`,  
`phim_anh`, `du_lich`, `suc_khoe`, `thoi_trang`, `game`, `am_thuc`

### 2. Crawl post content

```bash
bash crawl.sh          # 3 workers (mặc định)
bash crawl.sh 2        # 2 workers (RAM thấp hơn)

bash status.sh         # xem tiến độ
bash stop.sh           # dừng
```

Posts lưu tại `data/raw/{post_id}.json`. Mỗi worker có checkpoint riêng tại `data/checkpoint_{N}.json` — tự động resume sau crash.

### 3. Merge databases sau khi xong

```bash
.venv/bin/python3 merge_dbs.py
```

---

## Multi-machine sync (optional)

Để 2 máy crawl song song không trùng post, dùng Supabase làm shared checkpoint:

1. Tạo free project tại [supabase.com](https://supabase.com)
2. SQL Editor → chạy:
   ```sql
   CREATE TABLE scraped_ids (
       post_id TEXT PRIMARY KEY,
       scraped_at TIMESTAMPTZ DEFAULT now()
   );
   ALTER TABLE scraped_ids DISABLE ROW LEVEL SECURITY;

   CREATE TABLE target_urls (
       url TEXT PRIMARY KEY,
       category TEXT,
       added_at TIMESTAMPTZ DEFAULT now()
   );
   ALTER TABLE target_urls DISABLE ROW LEVEL SECURITY;
   ```
3. Project Settings → API → copy URL và anon key vào `.env`:
   ```
   supabase_db=https://xxx.supabase.co/rest/v1/
   supabase_key=eyJ...
   ```

Mỗi máy khi start sẽ tự fetch toàn bộ scraped_ids từ Supabase và merge vào local checkpoint.

**Phân công máy:**

| Máy | Việc |
|---|---|
| Máy A (collect) | `bash collect_urls.sh` → tự push URLs mới lên Supabase sau mỗi batch |
| Máy B (crawl) | `bash crawl.sh` → tự pull URLs từ Supabase nếu không có file local |

Máy B không cần `collect_urls.sh`. Khi `bash crawl.sh` được gọi lần đầu mà chưa có `targets_all_domains.yaml`, nó tự chạy `sync_targets.sh` để pull từ Supabase. Có thể cũng chạy `bash sync_targets.sh` thủ công để refresh danh sách.

---

## Data format

```
data/
  raw/          ← {post_id}.json
  media/        ← {post_id}/img_000.jpg
```

```json
{
  "post_id": "...",
  "node_features": { "text": "...", "image_urls": [...] },
  "engagement": { "like": 0, "comment_count": 0 },
  "graph_structure": {
    "comment_tree": [...],
    "edges_user_user": [...],
    "edges_comment_reply": [...]
  }
}
```

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

`config.yaml` — các tham số quan trọng:

```yaml
scraper:
  headless: true             # false để debug trong browser
  timeout: 15000             # page load timeout (ms)
  min_delay: 0.8             # delay giữa requests (giây)
  max_delay: 2.0

scraping:
  max_comments: 50           # comments/post
  post_timeout_seconds: 180  # timeout/post
```

---

## Tests

```bash
.venv/bin/pytest tests/ -q
.venv/bin/pytest tests/test_checkpoint.py -v   # test cụ thể
```
