#!/bin/bash
# Thu thập URLs từ tất cả domains — target 30k total cho GNN training
# Chạy qua đêm, tự resume nếu bị gián đoạn

TARGET_PER_PAGE=1500
MERGED="targets_all_domains.yaml"
LOG="logs/collect_all_domains.log"
mkdir -p logs

# Format: "URL|slug|category"
# Session được rotate sau mỗi page để tránh rate limit
PAGES=(
    # TIN TUC
    "https://www.facebook.com/congdongvnexpress/|vnexpress|tin_tuc"
    "https://www.facebook.com/baotuoitre/|tuoitre|tin_tuc"
    "https://www.facebook.com/baodantridientu/|dantri|tin_tuc"

    # GIAI TRI / SHOWBIZ
    "https://www.facebook.com/K14vn/|kenh14|giai_tri"
    "https://www.facebook.com/Theanh28/|theanh28|giai_tri"
    "https://www.facebook.com/yannews/|yannews|giai_tri"

    # HAI HUOC / MEME (PageWSS đã có)
    "https://www.facebook.com/blogtamsu.fanpage/|blogtamsu|hai_meme"
    "https://www.facebook.com/vngag.vn/|vngag|hai_meme"
    "https://www.facebook.com/ThoBayMau/|thobayMau|hai_meme"
    "https://www.facebook.com/nhavancucsuc/|nhavancucsuc|hai_meme"
    "https://www.facebook.com/thangfly/|thangfly|hai_meme"

    # THE THAO (trollbongda đã có)
    "https://www.facebook.com/NextSportsOfficial/|nextsports|the_thao"
    "https://www.facebook.com/thethao247.vn/|thethao247|the_thao"

    # AM THUC
    "https://www.facebook.com/FoodyVietnam/|foody|am_thuc"

    # CONG NGHE / GAMING
    "https://www.facebook.com/caothuvn/|caothu|cong_nghe"
    "https://www.facebook.com/gamek.vn/|gamek|cong_nghe"

    # LIFESTYLE / PHU NU
    "https://www.facebook.com/afamilyvccorp/|afamily|lifestyle"
    "https://www.facebook.com/evavietnam/|eva|lifestyle"

    # AM NHAC
    "https://www.facebook.com/zingmp3/|zingmp3|am_nhac"
    "https://www.facebook.com/MTP.Fan/|mtpfan|am_nhac"
)

SESSIONS=("cookies/session_2.json" "cookies/session_3.json" "cookies/session_4.json" "cookies/session_5.json" "cookies/session_6.json")

# Khởi tạo merged file từ những gì đã có
if [ -f "targets_all_5k.yaml" ]; then
    cp targets_all_5k.yaml $MERGED
    echo "[$(date)] Bắt đầu từ targets_all_5k.yaml" | tee -a $LOG
else
    echo "[]" > $MERGED
    echo "[$(date)] Bắt đầu fresh" | tee -a $LOG
fi

CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
echo "[$(date)] Hiện có: $CURRENT URLs" | tee -a $LOG

SESSION_IDX=0
PAGE_IDX=0

for entry in "${PAGES[@]}"; do
    URL="${entry%%|*}"
    REST="${entry#*|}"
    NAME="${REST%%|*}"
    CATEGORY="${REST##*|}"
    TMP="targets_tmp_${NAME}.yaml"

    # Rotate session sau mỗi 3 pages
    SESSION_FILE="${SESSIONS[$((SESSION_IDX % ${#SESSIONS[@]}))]}"
    PAGE_IDX=$((PAGE_IDX + 1))
    if [ $((PAGE_IDX % 3)) -eq 0 ]; then
        SESSION_IDX=$((SESSION_IDX + 1))
    fi

    echo "" | tee -a $LOG
    echo "[$(date)] [$CATEGORY] Collecting: $NAME (session: $SESSION_FILE, target: $TARGET_PER_PAGE)..." | tee -a $LOG

    # Temporarily override cookies file in collect_urls.py via env
    COOKIES_OVERRIDE="$SESSION_FILE" .venv/bin/python3 collect_urls.py "$URL" "$TMP" "$TARGET_PER_PAGE" 2>&1 | tee -a $LOG

    if [ -f "$TMP" ]; then
        ADDED=$(python3 - << PYEOF
import yaml

with open('$MERGED') as f:
    existing = yaml.safe_load(f) or []
existing_urls = {item['url'] for item in existing}

try:
    with open('$TMP') as f:
        new_items = yaml.safe_load(f) or []
except:
    new_items = []

added = [{'type': item['type'], 'url': item['url'], 'category': '$CATEGORY'} 
         for item in new_items if item['url'] not in existing_urls]
merged = existing + added

with open('$MERGED', 'w') as f:
    yaml.dump(merged, f, allow_unicode=True, default_flow_style=False)

print(len(added))
PYEOF
)
        rm -f "$TMP"
        CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
        echo "[$(date)] +$ADDED từ $NAME → tổng: $CURRENT URLs" | tee -a $LOG

        # Nghỉ 60s giữa các pages để tránh rate limit
        echo "[$(date)] Nghỉ 60s..." | tee -a $LOG
        sleep 60
    else
        echo "[$(date)] WARN: không có file output cho $NAME" | tee -a $LOG
    fi
done

CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
echo "" | tee -a $LOG
echo "[$(date)] ===== HOÀN THÀNH =====" | tee -a $LOG
echo "[$(date)] Tổng: $CURRENT URLs → $MERGED" | tee -a $LOG

# Thống kê theo category
python3 - << PYEOF
import yaml
from collections import Counter
d = yaml.safe_load(open('$MERGED')) or []
cats = Counter(item.get('category', 'unknown') for item in d)
print("\nThống kê theo category:")
for cat, count in sorted(cats.items()):
    print(f"  {cat}: {count}")
PYEOF
