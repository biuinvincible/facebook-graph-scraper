"""Auto-login Facebook và lưu cookies vào file."""
import asyncio
import json
import sys
import os
sys.path.insert(0, ".")

from playwright.async_api import async_playwright

COOKIES_FILE = sys.argv[1] if len(sys.argv) > 1 else "cookies/session.json"

# Lấy credentials từ args hoặc env
EMAIL    = sys.argv[2] if len(sys.argv) > 2 else os.getenv("FB_EMAIL", "")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.getenv("FB_PASSWORD", "")


async def login():
    if not EMAIL or not PASSWORD:
        print("Usage: python login.py <cookies_file> <email> <password>")
        print("   or: FB_EMAIL=... FB_PASSWORD=... python login.py <cookies_file>")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=50,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1280,800"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        print(f"Đang login với {EMAIL} ...")
        await page.goto("https://www.facebook.com/login", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Điền credentials bằng type() để trigger React state
        await page.wait_for_selector('[name="email"]', timeout=10000)
        await page.click('[name="email"]')
        await page.type('[name="email"]', EMAIL, delay=50)
        await asyncio.sleep(0.5)
        await page.click('[name="pass"]')
        await page.type('[name="pass"]', PASSWORD, delay=50)
        await asyncio.sleep(0.8)

        # Submit — thử các selector khác nhau, fallback Enter
        submitted = False
        for sel in [
            '[name="login"]',
            'button[type="submit"]',
            'button:has-text("Đăng nhập")',
            'button:has-text("Log in")',
            'button:has-text("Log In")',
            '[data-testid="royal_login_button"]',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            await page.keyboard.press("Enter")

        # Chờ redirect về home
        try:
            await page.wait_for_url("**/facebook.com/**", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(4)

        # Check 2FA hoặc checkpoint — poll cho đến khi c_user xuất hiện (tối đa 3 phút)
        current_url = page.url
        if "checkpoint" in current_url or "two_step" in current_url or "login" in current_url:
            print(f"\nCần xác thực thêm: {current_url}")
            print("Đang chờ login hoàn tất (tối đa 3 phút)...")
            for _ in range(180):  # poll mỗi giây
                await asyncio.sleep(1)
                cookies = await context.cookies()
                if any(c["name"] == "c_user" for c in cookies):
                    break

        # Verify
        cookies = await context.cookies()
        c_user = next((c["value"] for c in cookies if c["name"] == "c_user"), None)
        if not c_user:
            print("Login thất bại — không tìm thấy c_user cookie.")
            await browser.close()
            return

        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        print(f"OK — {len(cookies)} cookies → {COOKIES_FILE} (c_user={c_user})")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(login())
