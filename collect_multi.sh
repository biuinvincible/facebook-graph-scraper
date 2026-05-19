#!/bin/bash
TARGET=5000
MERGED="targets_all_5k.yaml"
LOG="logs/collect_multi.log"
mkdir -p logs

# Dùng | làm separator thay vì : để tránh conflict với https://
PAGES=(
    "https://www.facebook.com/blogtamsu.fanpage/|blogtamsu"
    "https://www.facebook.com/trollbongda/|trollbongda"
    "https://www.facebook.com/K14vn/|kenh14"
    "https://www.facebook.com/afamilyvccorp/|afamily"
    "https://www.facebook.com/FoodyVietnam/|foody"
)

cp targets_pagewss_all.yaml $MERGED
CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
echo "[$(date)] Start: $CURRENT URLs" | tee -a $LOG

for entry in "${PAGES[@]}"; do
    URL="${entry%%|*}"
    NAME="${entry##*|}"
    TMP="targets_tmp_${NAME}.yaml"

    if [ "$CURRENT" -ge "$TARGET" ]; then
        echo "[$(date)] Reached $TARGET — done" | tee -a $LOG
        break
    fi

    NEED=$((TARGET - CURRENT + 200))
    echo "[$(date)] Collecting from $NAME (need ~$NEED)..." | tee -a $LOG

    .venv/bin/python3 collect_urls.py "$URL" "$TMP" "$NEED" 2>&1 | tee -a $LOG

    if [ -f "$TMP" ]; then
        python3 - << PYEOF
import yaml

with open('$MERGED') as f:
    existing = yaml.safe_load(f) or []
existing_urls = {item['url'] for item in existing}

with open('$TMP') as f:
    new_items = yaml.safe_load(f) or []

added = [item for item in new_items if item['url'] not in existing_urls]
merged = existing + added

with open('$MERGED', 'w') as f:
    yaml.dump(merged, f, allow_unicode=True, default_flow_style=False)

print(f"  +{len(added)} new from $NAME → total {len(merged)}")
PYEOF
        rm -f "$TMP"
        CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
        echo "[$(date)] Total now: $CURRENT URLs" | tee -a $LOG
    fi
done

CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
echo "[$(date)] Final: $CURRENT URLs saved to $MERGED" | tee -a $LOG
