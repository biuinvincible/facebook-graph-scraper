#!/bin/bash
# Xem tiến độ crawl
cd "$(dirname "$0")"
POSTS=$(ls data/raw/*.json 2>/dev/null | wc -l)
WORKERS=$(ps aux | grep 'main.py scrape' | grep -v grep | wc -l)
LATEST=$(ls -lt data/raw/*.json 2>/dev/null | head -1 | awk '{print $6,$7,$8}')
SIZE=$(du -sh data/raw/ 2>/dev/null | cut -f1)

echo "=============================="
echo "  Posts   : $POSTS"
echo "  Workers : $WORKERS running"
echo "  Latest  : ${LATEST:-N/A}"
echo "  Size    : ${SIZE:-0}"
echo "=============================="
for i in 0 1 2 3; do
    F="data/checkpoint_${i}.json"
    [ -f "$F" ] && n=$(python3 -c "import json; print(len(json.load(open('$F')).get('scraped_ids',[])))" 2>/dev/null) && echo "  W${i}      : $n posts"
done
