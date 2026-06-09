#!/bin/bash
# Xem tiến độ thu thập URLs
cd "$(dirname "$0")"

RUNNING=$(screen -ls 2>/dev/null | grep -c "collect" || echo 0)
BROWSERS=$(ps aux | grep chromium | grep -v grep | wc -l)

python3 -c "
import yaml
from collections import Counter
data = yaml.safe_load(open('targets_all_domains.yaml')) or []
cats = Counter(x.get('category','?') for x in data if isinstance(x, dict))
total = sum(cats.values())
target = 65000
pct = total / target * 100

print('==============================')
print(f'  URLs    : {total:,} / ~{target:,} ({pct:.1f}%)')
print(f'  Screen  : $([ $RUNNING -gt 0 ] && echo running || echo stopped)')
print(f'  Browsers: $BROWSERS')
print('------------------------------')
for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
    bar = '█' * int(n / 500)
    print(f'  {cat:20} {n:>6,}  {bar}')
print('==============================')
"
