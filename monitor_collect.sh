#!/bin/bash
# Tự động restart collect khi crash, chạy đến khi xong tất cả batches
cd "$(dirname "$0")"

BATCHES=("pages_batch_fill.yaml")
OUTPUT="targets_all_domains.yaml"
LOG="logs/monitor_collect.log"
mkdir -p logs

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

for BATCH in "${BATCHES[@]}"; do
    while true; do
        # Kiểm tra batch này đã xong chưa dựa vào số URLs tăng
        BEFORE=$(python3 -c "import yaml; data=yaml.safe_load(open('$OUTPUT')); print(len([x for x in data if isinstance(x,dict)]))" 2>/dev/null)

        log "Chạy $BATCH (URLs hiện tại: $BEFORE)..."
        .venv/bin/python3 collect_urls.py --parallel "$BATCH" "$OUTPUT" 2>&1 | tee -a "$LOG"
        EXIT=${PIPESTATUS[0]}

        AFTER=$(python3 -c "import yaml; data=yaml.safe_load(open('$OUTPUT')); print(len([x for x in data if isinstance(x,dict)]))" 2>/dev/null)
        ADDED=$((AFTER - BEFORE))

        log "$BATCH xong. Exit=$EXIT, +$ADDED URLs (total: $AFTER)"

        # Nếu process xong bình thường (exit 0) thì sang batch tiếp
        if [ $EXIT -eq 0 ]; then
            log "✅ $BATCH hoàn thành"
            break
        else
            log "⚠️  Crash (exit $EXIT), restart sau 30s..."
            sleep 30
        fi
    done
done

log "=== TẤT CẢ XONG ==="
