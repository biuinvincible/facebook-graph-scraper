#!/bin/bash
# Dừng crawl, checkpoint đã lưu an toàn
cd "$(dirname "$0")"
screen -S scraper -X quit 2>/dev/null
kill -9 $(ps aux | grep -E "main.py|parallel_scrape|chrome-linux" | grep -v grep | awk '{print $2}') 2>/dev/null
sleep 2
echo "🛑 Đã dừng. Posts đã lưu: $(ls data/raw/*.json 2>/dev/null | wc -l)"
