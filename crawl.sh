#!/bin/bash
# ── Facebook Graph Crawler ────────────────────────────────────────────────────
# Usage: bash crawl.sh [workers]
# Default: 2 workers (stable). Max recommended: 3 nếu RAM > 8GB.

WORKERS=${1:-3}
TARGETS="targets_all_domains.yaml"
LOG="logs/orchestrator.log"
SCREEN_NAME="scraper"

cd "$(dirname "$0")"
mkdir -p logs

# ── Check if already running ──────────────────────────────────────────────────
if screen -ls | grep -q "$SCREEN_NAME"; then
    echo "⚠️  Scraper đang chạy rồi (screen session '$SCREEN_NAME' tồn tại)"
    echo "   Dùng 'screen -r $SCREEN_NAME' để vào xem"
    echo "   Dùng 'bash stop.sh' để dừng"
    exit 1
fi

# ── Status hiện tại ───────────────────────────────────────────────────────────
POSTS=$(ls data/raw/*.json 2>/dev/null | wc -l)
echo "📦 Posts hiện tại: $POSTS"
echo "🚀 Bắt đầu crawl với $WORKERS workers..."
echo "   Logs: $LOG"
echo "   Check tiến độ: bash status.sh"
echo "   Dừng lại:      bash stop.sh"
echo ""

# ── Start ─────────────────────────────────────────────────────────────────────
screen -dmS "$SCREEN_NAME" bash -c \
    ".venv/bin/python3 parallel_scrape.py $TARGETS $WORKERS > $LOG 2>&1"

sleep 5
RUNNING=$(ps aux | grep 'main.py scrape' | grep -v grep | wc -l)
if [ "$RUNNING" -gt 0 ]; then
    echo "✅ $RUNNING workers đang chạy"
else
    echo "❌ Không có worker nào start được — kiểm tra logs/$LOG"
fi
