#!/bin/bash
# ── Facebook Graph Scraper — One-command Setup ────────────────────────────────
# Tested on: Ubuntu 22.04+, Debian 12+, WSL2
# Requirements: Python 3.10+, git
#
# Usage: bash setup.sh

set -e
cd "$(dirname "$0")"

echo "=== Facebook Graph Scraper Setup ==="
echo ""

# ── Python version check ──────────────────────────────────────────────────────
PY=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
PY_MAJOR=$(echo $PY | cut -d. -f1)
PY_MINOR=$(echo $PY | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "❌ Python 3.10+ required (found $PY)"
    exit 1
fi
echo "✅ Python $PY"

# ── System dependencies ───────────────────────────────────────────────────────
if command -v apt-get &>/dev/null; then
    echo "📦 Installing system packages..."
    sudo apt-get install -y -q \
        tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libasound2 \
        screen 2>/dev/null || true
    echo "✅ System packages installed"
fi

# ── Python virtual environment ────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "🐍 Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "✅ Virtual environment ready"

# ── Python packages ───────────────────────────────────────────────────────────
echo "📦 Installing Python packages..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✅ Python packages installed"

# ── Playwright browsers ───────────────────────────────────────────────────────
echo "🌐 Installing Playwright Chromium..."
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium 2>/dev/null || true
echo "✅ Playwright Chromium ready"

# ── Directory structure ───────────────────────────────────────────────────────
mkdir -p data/raw data/media data/processed logs cookies
touch data/.gitkeep cookies/.gitkeep logs/.gitkeep
echo "✅ Directories created"

# ── Environment file ──────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Created .env from template — fill in your credentials:"
    echo "     FB_EMAIL, FB_PASSWORD (required)"
    echo "     supabase_db, supabase_key (optional, for multi-machine sync)"
else
    echo "✅ .env already exists"
fi

# ── Script permissions ────────────────────────────────────────────────────────
chmod +x crawl.sh stop.sh status.sh collect_urls.sh stop_collect.sh status_collect.sh 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env:        nano .env"
echo "  2. Login (lặp cho mỗi session file):"
echo "       python login.py cookies/session_2.json"
echo "       python login.py cookies/session_3.json"
echo "       python login.py cookies/session_4.json"
echo "  3. Collect URLs:     bash collect_urls.sh"
echo "  4. Crawl posts:      bash crawl.sh"
echo "  5. Check tiến độ:   bash status.sh          # posts"
echo "                       bash status_collect.sh  # urls"
