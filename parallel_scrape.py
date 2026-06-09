"""
Parallel scraper: chia targets thành N chunks, chạy N processes song song.
Mỗi process dùng 1 session riêng, 1 checkpoint riêng.
Data ghi chung vào data/raw/ (mỗi post có unique filename = post_id).
"""
import asyncio
import sys
import os
import yaml
import subprocess
import tempfile
from pathlib import Path
from math import ceil


def split_targets(targets: list, n: int) -> list[list]:
    """Chia targets thành n chunks bằng nhau."""
    size = ceil(len(targets) / n)
    return [targets[i:i+size] for i in range(0, len(targets), size)]


def create_config(session_file: str, checkpoint_file: str, worker_id: int) -> str:
    """Tạo config.yaml riêng cho mỗi worker."""
    base = yaml.safe_load(Path("config.yaml").read_text())
    base["scraper"]["cookies_file"] = session_file
    base["protection"]["checkpoint_file"] = checkpoint_file
    # DB riêng per worker → tránh SQLite lock
    base["storage"]["db_path"] = f"data/worker_{worker_id}.db"
    cfg_path = f"/tmp/config_worker_{worker_id}.yaml"
    Path(cfg_path).write_text(yaml.dump(base))
    return cfg_path


async def run_worker(worker_id: int, targets: list, session_file: str):
    """Chạy 1 scraper process."""
    # Ghi chunk targets ra file tạm
    chunk_file = f"/tmp/targets_chunk_{worker_id}.yaml"
    Path(chunk_file).write_text(yaml.dump(targets, allow_unicode=True, default_flow_style=False))

    checkpoint_file = f"data/checkpoint_{worker_id}.json"
    config_file = create_config(session_file, checkpoint_file, worker_id)

    cmd = [
        "nice", "-n", "10",
        ".venv/bin/python3", "main.py", "scrape",
        "--from-file", chunk_file,
        "--config", config_file,
    ]

    print(f"[Worker {worker_id}] Starting: {len(targets)} URLs | session={session_file}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd="/mnt/d/facebook-scraper",
    )

    log_file = Path(f"logs/worker_{worker_id}.log")
    log_file.parent.mkdir(exist_ok=True)

    async with asyncio.timeout(None):
        with open(log_file, "ab") as lf:
            async for line in proc.stdout:
                lf.write(line)
                lf.flush()

    await proc.wait()
    print(f"[Worker {worker_id}] Done (exit {proc.returncode})")
    return proc.returncode


def load_targets(targets_file: str) -> list:
    """Load targets từ YAML local, hoặc pull từ Supabase nếu file không tồn tại."""
    path = Path(targets_file)
    if path.exists():
        targets = yaml.safe_load(path.read_text()) or []
        if targets:
            return targets
        print(f"⚠️  {targets_file} trống — thử pull từ Supabase...")

    # Fallback: pull từ Supabase
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from src.utils.supabase_sync import from_env
        sb = from_env()
        if not sb:
            print(f"❌ {targets_file} không tồn tại và chưa cấu hình Supabase")
            sys.exit(1)
        print("📥 Pulling target URLs từ Supabase...")
        items = sb.pull_target_urls()
        if not items:
            print("❌ Supabase trả về 0 URLs — chạy collect_urls.sh trước")
            sys.exit(1)
        # Lưu local để dùng lại
        path.write_text(yaml.dump(items, allow_unicode=True, default_flow_style=False))
        print(f"✓ Pulled {len(items)} URLs từ Supabase → {targets_file}")
        return items
    except Exception as e:
        print(f"❌ Không load được targets: {e}")
        sys.exit(1)


async def main():
    targets_file = sys.argv[1] if len(sys.argv) > 1 else "targets_all_domains.yaml"
    n_workers    = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    sessions = [
        "cookies/session_2.json",
        "cookies/session_3.json",
        "cookies/session_4.json",
        "cookies/session_5.json",
        "cookies/session_6.json",
    ]

    targets = load_targets(targets_file)
    chunks  = split_targets(targets, n_workers)

    print(f"Parallel scrape: {len(targets)} URLs → {n_workers} workers")
    for i, chunk in enumerate(chunks):
        print(f"  Worker {i}: {len(chunk)} URLs | {sessions[i % len(sessions)]}")

    Path("data/raw").mkdir(parents=True, exist_ok=True)
    Path("data/media").mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    tasks = [
        run_worker(i, chunks[i], sessions[i % len(sessions)])
        for i in range(len(chunks))
    ]
    results = await asyncio.gather(*tasks)
    print(f"\nAll workers done. Exit codes: {results}")

    # Merge DBs
    print("\nMerging databases...")
    os.system("python3 merge_dbs.py")


if __name__ == "__main__":
    asyncio.run(main())
