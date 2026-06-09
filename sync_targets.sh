#!/bin/bash
# Pull target URLs từ Supabase về targets_all_domains.yaml
# Dùng trên máy chỉ crawl posts (không collect URLs)
cd "$(dirname "$0")"

OUTPUT="${1:-targets_all_domains.yaml}"
echo "Pulling target URLs từ Supabase → $OUTPUT ..."

.venv/bin/python3 -c "
import os, sys, yaml
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

output = '$OUTPUT'

from src.utils.supabase_sync import from_env
sb = from_env()
if not sb:
    print('❌ Chưa cấu hình supabase_db + supabase_key trong .env')
    sys.exit(1)

items = sb.pull_target_urls()
if not items:
    print('⚠️  Supabase trả về 0 URLs — chạy collect_urls.sh trước')
    sys.exit(1)

Path(output).write_text(yaml.dump(items, allow_unicode=True, default_flow_style=False))

from collections import Counter
cats = Counter(x.get('category','?') for x in items)
print(f'✓ {len(items):,} URLs → {output}')
for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f'  {cat:20} {n:,}')
"
