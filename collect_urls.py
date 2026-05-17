"""
Thu thập post URLs từ Facebook page/profile bằng cách scroll feed.

Usage đơn:
  python collect_urls.py <page_url> [output_file] [max_posts]

Usage parallel (nhiều pages cùng lúc, mỗi page 1 session riêng):
  python collect_urls.py --parallel <pages_config.yaml> <output_file>

  pages_config.yaml format:
    - url: https://www.facebook.com/PageWSS/
      session: cookies/session_2.json
      category: hai_meme
    - url: https://www.facebook.com/trollbongda/
      session: cookies/session_3.json
      category: the_thao
"""
import asyncio
import sys
import json
import os
import yaml
from pathlib import Path
sys.path.insert(0, ".")

JS_COLLECT = """
    (slug) => {
        const seen = new Set();
        const result = [];
        const slugLow = slug ? slug.toLowerCase() : '';
        document.querySelectorAll('a[href]').forEach(a => {
            const h = a.href;
            if (!h || h.includes('/reel/') || h.includes('/videos/')) return;
            if (h.includes('/groups/')) return;

            // Chỉ lấy native post URLs — /slug/posts/ID hoặc story_fbid=
            const isSlugPost = slugLow && (
                h.toLowerCase().includes('/' + slugLow + '/posts/') ||
                h.toLowerCase().includes('/' + slugLow + '/permalink/')
            );
            const isPermalink = h.includes('story_fbid=');
            const isGenericPost = !slugLow && h.includes('/posts/');

            if (!isSlugPost && !isPermalink && !isGenericPost) return;

            let clean;
            if (isPermalink && h.includes('story_fbid=')) {
                try {
                    const u = new URL(h);
                    const fbid = u.searchParams.get('story_fbid');
                    const id   = u.searchParams.get('id');
                    clean = fbid
                        ? (id
                            ? `https://www.facebook.com/permalink.php?story_fbid=${fbid}&id=${id}`
                            : `https://www.facebook.com/permalink.php?story_fbid=${fbid}`)
                        : h.split('?')[0];
                } catch(e) { clean = h.split('?')[0]; }
            } else {
                clean = h.split('?')[0];
            }
            if (!seen.has(clean)) { seen.add(clean); result.push(clean); }
        });
        return result;
    }
"""


async def collect_one(
    page_url: str,
    max_posts: int,
    cookies_file: str,
    category: str = "",
    shared_seen: set = None,
    lock: asyncio.Lock = None,
    playwright=None,           # shared playwright instance (optional)
) -> list:
    """Collect URLs từ 1 page. Nhận playwright instance từ ngoài nếu chạy parallel."""
    from urllib.parse import urlparse

    cookies = json.loads(Path(cookies_file).read_text())
    _slug = urlparse(page_url).path.strip("/").split("/")[0]
    collected = []

    async def _run(p):
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        print(f"[{_slug}] Loading {page_url} ...")
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[{_slug}] Navigation failed: {e}")
            await browser.close()
            return

        await asyncio.sleep(5)

        local_seen: set = set()
        no_new_streak = 0
        scroll_count = 0

        while len(collected) < max_posts:
            links = await page.evaluate(JS_COLLECT, _slug)

            # Tách: "page còn content mới không" (local_seen) vs "đã có trong dataset" (shared_seen)
            # → dừng scroll khi PAGE hết content, không phải khi tất cả đã có trong dataset
            new_to_session = [u for u in links if u not in local_seen]
            for u in new_to_session:
                local_seen.add(u)

            if not new_to_session:
                no_new_streak += 1
                if no_new_streak >= 8:
                    print(f"[{_slug}] Dừng sau 8 scrolls không mới — {len(collected)} URLs")
                    break
            else:
                no_new_streak = 0

            for url in new_to_session:
                if len(collected) >= max_posts:
                    break
                if shared_seen is not None and lock is not None:
                    async with lock:
                        if url in shared_seen:
                            continue
                        shared_seen.add(url)
                collected.append({"type": "post", "url": url, "category": category})
                if len(collected) % 50 == 1:
                    print(f"[{_slug}] {len(collected)}/{max_posts} URLs")

            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(2)
            scroll_count += 1
            if scroll_count % 10 == 0:
                print(f"[{_slug}] scroll={scroll_count}, collected={len(collected)}")

        await browser.close()
        print(f"[{_slug}] Done: {len(collected)} URLs")

    if playwright is not None:
        await _run(playwright)
    else:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            await _run(p)

    return collected


async def collect_parallel(pages_config: list, output_file: str):
    """Chạy nhiều pages song song dùng 1 playwright instance chung."""
    from playwright.async_api import async_playwright

    existing = []
    if Path(output_file).exists():
        existing = yaml.safe_load(Path(output_file).read_text()) or []
    shared_seen = {item["url"] for item in existing if isinstance(item, dict) and "url" in item}
    print(f"Existing: {len(shared_seen)} URLs | Starting {len(pages_config)} parallel workers...")

    lock = asyncio.Lock()

    async with async_playwright() as p:
        # Stagger starts 30s apart — tránh FB rate-limit khi nhiều browsers mở cùng lúc
        async def staggered(cfg, delay):
            if delay > 0:
                await asyncio.sleep(delay)
            return await collect_one(
                page_url=cfg["url"],
                max_posts=cfg.get("max_posts", 1500),
                cookies_file=cfg["session"],
                category=cfg.get("category", ""),
                shared_seen=shared_seen,
                lock=lock,
                playwright=p,
            )

        tasks = [staggered(cfg, i * 30) for i, cfg in enumerate(pages_config)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_new = []
    for cfg, result in zip(pages_config, results):
        if isinstance(result, Exception):
            print(f"ERROR [{cfg['url']}]: {result}")
        else:
            all_new.extend(result)
            print(f"  +{len(result)} từ {cfg['url'].split('/')[-2]}")

    merged = existing + all_new
    Path(output_file).write_text(
        yaml.dump(merged, allow_unicode=True, default_flow_style=False)
    )
    print(f"\n✓ Total: {len(merged)} URLs → {output_file}")
    print(f"  New this run: {len(all_new)}")

    # Thống kê theo category
    from collections import Counter
    cats = Counter(item.get("category", "unknown") for item in merged)
    print("\nTheo category:")
    for cat, count in sorted(cats.items()):
        print(f"  {cat:15}: {count}")


async def collect_single(page_url: str, output_file: str, max_posts: int):
    """Single-page mode (backward compatible)."""
    cookies_file = os.environ.get("COOKIES_OVERRIDE", "cookies/session_2.json")

    existing = []
    if Path(output_file).exists():
        existing = yaml.safe_load(Path(output_file).read_text()) or []
    shared_seen = {item["url"] if isinstance(item, dict) else item for item in existing}
    print(f"Existing: {len(shared_seen)} URLs")

    lock = asyncio.Lock()
    collected = await collect_one(
        page_url=page_url,
        max_posts=max_posts,
        cookies_file=cookies_file,
        shared_seen=shared_seen,
        lock=lock,
    )

    all_items = existing + collected
    Path(output_file).write_text(
        yaml.dump(all_items, allow_unicode=True, default_flow_style=False)
    )
    print(f"\n✓ Saved {len(all_items)} URLs → {output_file}")
    print(f"  Newly collected: {len(collected)}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--parallel":
        # python collect_urls.py --parallel pages_config.yaml output.yaml
        config_file = sys.argv[2] if len(sys.argv) > 2 else "pages_config.yaml"
        output_file = sys.argv[3] if len(sys.argv) > 3 else "targets_collected.yaml"
        pages_config = yaml.safe_load(Path(config_file).read_text())
        asyncio.run(collect_parallel(pages_config, output_file))
    else:
        # python collect_urls.py <url> [output] [max]
        page_url   = sys.argv[1] if len(sys.argv) > 1 else "https://www.facebook.com/PageWSS/"
        output_file = sys.argv[2] if len(sys.argv) > 2 else "targets.yaml"
        max_posts  = int(sys.argv[3]) if len(sys.argv) > 3 else 50
        asyncio.run(collect_single(page_url, output_file, max_posts))
