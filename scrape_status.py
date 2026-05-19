"""Quick status check across all workers."""
import os
from pathlib import Path

def status():
    raw_dir = Path("data/raw")
    n_json = len(list(raw_dir.glob("*.json"))) if raw_dir.exists() else 0

    print(f"\n{'='*50}")
    print(f"  Scraped posts: {n_json}")
    print(f"{'='*50}")

    # Per-worker progress from logs
    for i in range(5):
        log = Path(f"logs/worker_{i}.log")
        if not log.exists():
            continue
        lines = log.read_text().splitlines()
        # Find last "Scraped post" line
        scraped_lines = [l for l in lines if "Scraped post" in l or "new posts scraped" in l]
        last = scraped_lines[-1] if scraped_lines else "starting..."
        chk = Path(f"data/checkpoint_{i}.json")
        n_chk = 0
        if chk.exists():
            import json
            try:
                d = json.loads(chk.read_text())
                n_chk = len(d.get("scraped_ids", []))
            except:
                pass
        print(f"  Worker {i}: {n_chk} posts | {last[-80:]}")

    # Media size
    media = Path("data/media")
    if media.exists():
        size = sum(f.stat().st_size for f in media.rglob("*") if f.is_file())
        print(f"\n  Media: {size/1024/1024:.1f} MB")

    print()

if __name__ == "__main__":
    status()
