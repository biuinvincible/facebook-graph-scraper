#!/bin/bash
# Resume — chạy lại các pages trả về 0, + MTP.Fan bị interrupt

MERGED="targets_all_domains.yaml"
LOG="logs/collect_all_domains.log"
TARGET_PER_PAGE=1500

# Pages cần retry (trả về 0 hoặc crash)
PAGES=(
    "https://www.facebook.com/congdongvnexpress/|vnexpress|tin_tuc|cookies/session_2.json"
    "https://www.facebook.com/baotuoitre/|tuoitre|tin_tuc|cookies/session_3.json"
    "https://www.facebook.com/baodantridientu/|dantri|tin_tuc|cookies/session_4.json"
    "https://www.facebook.com/yannews/|yannews|giai_tri|cookies/session_5.json"
    "https://www.facebook.com/blogtamsu.fanpage/|blogtamsu|hai_meme|cookies/session_6.json"
    "https://www.facebook.com/NextSportsOfficial/|nextsports|the_thao|cookies/session_2.json"
    "https://www.facebook.com/thethao247.vn/|thethao247|the_thao|cookies/session_3.json"
    "https://www.facebook.com/FoodyVietnam/|foody|am_thuc|cookies/session_4.json"
    "https://www.facebook.com/caothuvn/|caothu|cong_nghe|cookies/session_5.json"
    "https://www.facebook.com/afamilyvccorp/|afamily|lifestyle|cookies/session_6.json"
    "https://www.facebook.com/evavietnam/|eva|lifestyle|cookies/session_2.json"
    "https://www.facebook.com/zingmp3/|zingmp3|am_nhac|cookies/session_3.json"
    "https://www.facebook.com/MTP.Fan/|mtpfan|am_nhac|cookies/session_4.json"
)

CURRENT=$(python3 -c "import yaml; d=yaml.safe_load(open('$MERGED')); print(len(d))")
echo "[$(date)] Resume từ: $CURRENT URLs" | tee -a $LOG

for entry in "${PAGES[@]}"; do
    IFS='|' read -r URL NAME CATEGORY SESSION <<< "$entry"
    TMP="targets_tmp_${NAME}.yaml"

    echo "" | tee -a $LOG
    echo "[$(date)] [$CATEGORY] Retry: $NAME (session: $SESSION)..." | tee -a $LOG

    COOKIES_OVERRIDE="$SESSION" .venv/bin/python3 collect_urls.py "$URL" "$TMP" "$TARGET_PER_PAGE" 2>&1 | tee -a $LOG

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
        echo "[$(date)] +$ADDED từ $NAME → tổng: $CURRENT" | tee -a $LOG
        sleep 60
    fi
done

python3 - << PYEOF
import yaml
from collections import Counter
d = yaml.safe_load(open('$MERGED')) or []
cats = Counter(item.get('category', 'unknown') for item in d)
print(f"\nTổng: {len(d)} URLs")
for cat, count in sorted(cats.items()):
    print(f"  {cat:15}: {count}")
PYEOF
