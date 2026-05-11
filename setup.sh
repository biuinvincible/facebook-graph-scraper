#!/bin/bash
# One-command setup for Facebook Graph Scraper

echo "=== Facebook Graph Scraper Setup ==="

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
playwright install-deps chromium

# Install Tesseract OCR (Ubuntu/Debian)
if command -v apt-get &> /dev/null; then
    sudo apt-get install -y tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng
    echo "Tesseract installed with Vietnamese language pack"
fi

# Copy .env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env file — please edit with your credentials"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your Facebook credentials"
echo "  2. Login: python main.py login"
echo "  3. Run:   python main.py scrape --target page --url https://www.facebook.com/vnexpress.net"
echo "  4. Stats: python main.py stats"
