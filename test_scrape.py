"""Quick test: scrape 5 posts from a Vietnamese news fanpage."""
import asyncio
import sys
sys.path.insert(0, ".")

from src.utils.browser import BrowserManager
from src.extractors.post_extractor import PostExtractor
from src.extractors.comment_extractor import CommentExtractor
from src.scrapers.page_scraper import PageScraper
from src.graph.edge_builder import EdgeBuilder
from src.graph.schema import UserNode
from src.storage.json_storage import JsonStorage
from src.storage.database import Database
import yaml

TARGET_URL   = "https://www.facebook.com/share/p/1C3UCReQNm/"
MAX_POSTS    = 1
SKIP_NO_TEXT = False
MAX_COMMENTS = 100
SKIP_TRUNCATED = False


async def get_post_links(page, page_slug: str = "") -> list[str]:
    """Đợi feed load, rồi collect link bài post — chỉ của target page."""
    for sel in ['[role="feed"]', '[role="article"]', '[data-pagelet*="FeedUnit"]']:
        try:
            await page.wait_for_selector(sel, timeout=8000)
            break
        except Exception:
            continue
    await asyncio.sleep(2)

    links = await page.evaluate("""
        (pageSlug) => {
            const postLinks = new Set();   // /posts/, /permalink/, story_fbid=
            const photoLinks = new Set();  // /photo/?fbid= fallback

            // Normalize slug để match: "PageWSS" → match href chứa "/PageWSS/"
            const slug = pageSlug ? pageSlug.toLowerCase() : '';

            document.querySelectorAll('[role="article"] a[href], a[href]').forEach(a => {
                const h = a.href;
                if (!h || h.includes('/reel/') || h.includes('/videos/')) return;

                // Nếu biết slug của page, chỉ lấy links của chính page đó
                if (slug) {
                    const hLow = h.toLowerCase();
                    // Phải chứa slug trong path (không phải query string)
                    if (!hLow.includes('/' + slug + '/') && !hLow.includes('/' + slug + '?')) return;
                }

                if ((h.includes('/posts/') || h.includes('/permalink/') || h.includes('story_fbid='))
                    && !h.includes('/groups/')) {
                    postLinks.add(h.split('?')[0]);
                } else if ((h.includes('/photo/?fbid=') || h.includes('/photo?fbid='))
                           && !h.includes('/set=')) {
                    photoLinks.add(h.split('&set=')[0]);
                }
            });

            // Ưu tiên post links, fallback sang photo links nếu không đủ
            const result = [...postLinks];
            if (result.length < 3) {
                for (const l of photoLinks) {
                    if (!result.includes(l)) result.push(l);
                }
            }
            return result;
        }
    """, page_slug)
    return links[:MAX_POSTS * 5]


async def run():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    scraper_cfg = cfg["scraper"].copy()
    scraper_cfg["headless"] = False
    scraper_cfg["slow_mo"] = 50
    scraper_cfg["cookies_file"] = "cookies/session_2.json"

    flat = {
        **scraper_cfg,
        "max_comments": MAX_COMMENTS,
        "max_replies_per_comment": 5,
        "scrape_replies": True,
        "download_media": True,
        "ocr_enabled": False,
        "storage": cfg.get("storage", {}),
    }

    pe = PostExtractor(flat)
    ce = CommentExtractor(flat)
    json_store = JsonStorage("data/json")
    edge_builder = EdgeBuilder()

    async with BrowserManager(scraper_cfg) as bm:
        context = bm._context
        page_scraper = PageScraper(context, flat)
        feed_page = await context.new_page()

        print(f"Loading {TARGET_URL} ...")

        # Nếu TARGET_URL là 1 post cụ thể → dùng trực tiếp, không cần scrape feed
        is_direct_post = any(p in TARGET_URL for p in ['/posts/', '/photo/?fbid=', '/permalink/', '/share/p/', '/share/'])
        if is_direct_post:
            post_links = [TARGET_URL]
            print(f"  Direct post URL: {TARGET_URL}")
        else:
            # Extract page slug từ URL để filter chỉ lấy posts của page đó
            from urllib.parse import urlparse
            _slug = urlparse(TARGET_URL).path.strip("/").split("/")[0]

            await feed_page.goto(TARGET_URL, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            page_url = feed_page.url
            print(f"  page url: {page_url}")

            # Scroll & collect progressively — dừng khi đủ link để pfbid còn hợp lệ
            post_links = []
            seen = set()
            for i in range(10):
                await feed_page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(2)
                batch = await get_post_links(feed_page, _slug)
                for l in batch:
                    if l not in seen:
                        seen.add(l)
                        post_links.append(l)
                if len(post_links) >= MAX_POSTS * 2:
                    break  # đủ rồi, navigate ngay khi pfbid còn fresh
        print(f"Found {len(post_links)} post links:")
        for l in post_links:
            print(f"  {l}")

        if not post_links:
            await feed_page.screenshot(path="data/debug_feed.png")
            print("No links found — xem data/debug_feed.png")
            return

        count = 0
        all_posts = []

        async with Database("data/facebook_graph.db") as db:
            for url in post_links:
                if count >= MAX_POSTS:
                    break

                print(f"\n[{count+1}/{MAX_POSTS}] {url[:80]}")
                tab = await context.new_page()
                try:
                    post = await pe.extract_from_url(tab, url)
                    if not post or (not post.raw_text and not post.image_urls):
                        print("  skip: no content")
                        continue
                    if SKIP_TRUNCATED and post.raw_text and post.raw_text.endswith('Xem thêm'):
                        print(f"  skip: text truncated — {repr(post.raw_text[:60])}")
                        continue
                    if SKIP_NO_TEXT and not post.raw_text and post.like_count == 0:
                        print(f"  skip: no text, no reactions")
                        continue

                    # Download ảnh của bài viết
                    post = await page_scraper.media_extractor.process_post_media(post)

                    print(f"  text    : {repr(post.raw_text[:100])}")
                    print(f"  imgs    : {len(post.image_urls)}")
                    rxn = f"like={post.like_count} love={post.love_count} haha={post.haha_count} wow={post.wow_count} sad={post.sad_count} angry={post.angry_count} care={post.care_count} → total={post.total_reactions()}"
                    print(f"  reactions: {rxn}")
                    print(f"  hashtags: {post.hashtags}")

                    comments, c_edges = await ce.extract_all_comments(tab, post.post_id)

                    # Download ảnh trong comments
                    for i, c in enumerate(comments):
                        if c.image_urls:
                            comments[i] = await page_scraper.media_extractor.process_comment_media(c, post.post_id)

                    print(f"  comments: {len(comments)}")
                    for c in comments[:2]:
                        print(f"    [{c.author_name}]: {(c.raw_text or '')[:60]}")
                    imgs_in_comments = sum(len(c.local_image_paths) for c in comments)
                    if imgs_in_comments:
                        print(f"  comment imgs downloaded: {imgs_in_comments}")

                    # Build author UserNode từ post metadata
                    author_node = UserNode(
                        user_id=post.author_id or "",
                        display_name=post.author_name or "",
                    ) if post.author_id else None
                    sample = page_scraper._build_sample(post, author_node, comments, c_edges)
                    all_posts.append(post)

                    u_post = len(sample.edges_user_post)
                    u_user = len(sample.edges_user_user)
                    u_cmt  = len(sample.edges_user_comment)
                    print(f"  edges   : user→post={u_post}, user→user={u_user}, user→comment={u_cmt}")

                    path = await json_store.save_sample(sample)
                    await db.save_sample(sample, json_path=path)
                    print(f"  saved   : {path}")
                    count += 1

                except Exception as e:
                    print(f"  error: {e}")
                finally:
                    await tab.close()
                    await asyncio.sleep(1.5)

            # Build Post→Post similarity edges
            if len(all_posts) > 1:
                pp_edges = edge_builder.build_post_post_edges(all_posts)
                for edge in pp_edges:
                    await db.save_post_post_edge(edge)
                print(f"\nPost-post edges built: {len(pp_edges)}")

            stats = await db.get_stats()

        print(f"\n=== XONG: {count}/{MAX_POSTS} posts scraped ===")
        print(f"DB stats: {stats}")


if __name__ == "__main__":
    asyncio.run(run())
