#!/bin/bash
# Dừng URL collection
cd "$(dirname "$0")"
screen -S collect -X quit 2>/dev/null
pkill -f "collect_urls.py" 2>/dev/null
pkill -f "chromium.*collect" 2>/dev/null
sleep 2

URLS=$(python3 -c "
import yaml
data = yaml.safe_load(open('targets_all_domains.yaml')) or []
print(sum(1 for x in data if isinstance(x, dict)))
" 2>/dev/null || echo "?")
echo "🛑 Đã dừng. URLs đã lưu: $URLS"
