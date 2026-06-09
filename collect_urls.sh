#!/bin/bash
# ── Facebook URL Collector ────────────────────────────────────────────────────
# Thu thập post URLs từ các pages và lưu vào targets file.
#
# Usage:
#   bash collect_urls.sh              → chạy tất cả batches còn lại
#   bash collect_urls.sh 3            → chạy từ batch 3
#   bash collect_urls.sh 3 5          → chạy batch 3 đến 5

SCREEN_NAME="collect"
OUTPUT="targets_all_domains.yaml"
START_BATCH=${1:-1}
END_BATCH=${2:-8}

cd "$(dirname "$0")"
mkdir -p logs

# ── Check if already running ──────────────────────────────────────────────────
if screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
    echo "⚠️  URL collector đang chạy rồi (screen '$SCREEN_NAME')"
    echo "   Xem live:  screen -r $SCREEN_NAME"
    echo "   Dừng lại:  bash stop_collect.sh"
    exit 1
fi

# ── Validate batch range ──────────────────────────────────────────────────────
MISSING=""
for i in $(seq $START_BATCH $END_BATCH); do
    [ ! -f "pages_batch_${i}.yaml" ] && MISSING="$MISSING batch_${i}"
done
if [ -n "$MISSING" ]; then
    echo "❌ Không tìm thấy config:$MISSING"
    exit 1
fi

# ── Status hiện tại ───────────────────────────────────────────────────────────
TOTAL_URLS=$(python3 -c "
import yaml
data = yaml.safe_load(open('$OUTPUT')) or []
print(sum(1 for x in data if isinstance(x, dict)))
" 2>/dev/null || echo "?")
echo "🔗 URLs hiện tại: $TOTAL_URLS"
echo "🚀 Chạy batch $START_BATCH → $END_BATCH (output: $OUTPUT)"
echo "   Xem live:  screen -r $SCREEN_NAME"
echo "   Dừng lại:  bash stop_collect.sh"
echo ""

# ── Start ─────────────────────────────────────────────────────────────────────
screen -dmS "$SCREEN_NAME" bash -c "
cd $(pwd)
for i in \$(seq $START_BATCH $END_BATCH); do
    echo \"\"
    echo \"=== BATCH \$i / $END_BATCH — \$(date) ===\"
    .venv/bin/python3 collect_urls.py --parallel pages_batch_\${i}.yaml $OUTPUT
    echo \"=== Batch \$i xong — \$(date) ===\"
    sleep 60
done
echo \"\"
echo \"=== HOÀN THÀNH — \$(date) ===\"
python3 -c \"
import yaml
from collections import Counter
data = yaml.safe_load(open('$OUTPUT'))
cats = Counter(x.get('category','?') for x in data if isinstance(x, dict))
total = sum(cats.values())
print(f'Total URLs: {total:,}')
for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f'  {cat}: {n:,}')
\"
"

sleep 5
if screen -ls 2>/dev/null | grep -q "$SCREEN_NAME"; then
    echo "✅ Đang chạy"
else
    echo "❌ Không start được — kiểm tra lại"
fi
