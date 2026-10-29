import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(r"D:\Doc\TestDev_Route")
HTML = ROOT / "测试开发知识库.html"
OUT = ROOT / "site_build"
URL = "file:///" + quote(str(HTML).replace("\\", "/"))

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

    page.goto(URL, wait_until="load")
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / "shot_home.png"))
    print("nav items:", page.locator(".nav-item").count())
    print("cards:", page.locator(".card").count())

    page.goto(URL + "#/api-design", wait_until="load")
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / "shot_article.png"))
    print("article code blocks:", page.locator(".code-wrap").count())
    print("article tables:", page.locator(".doc-body table").count())
    print("toc links:", page.locator("#tocList a").count())
    print("title:", page.title())

    page.click("#themeBtn")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "shot_dark.png"))
    page.click("#themeBtn")

    page.goto(URL, wait_until="load")
    page.wait_for_timeout(300)
    page.fill("#searchInput", "幂等")
    page.wait_for_timeout(600)
    n = page.locator(".sr-item").count()
    print("search hits:", n)
    page.screenshot(path=str(OUT / "shot_search.png"))
    if n == 0:
        errors.append("search returned 0")

    page.goto(URL + "#/mysql", wait_until="load")
    page.wait_for_timeout(500)
    page.locator(".copy-btn").first.click()
    page.wait_for_timeout(250)
    print("copy btn after click:", page.locator(".copy-btn").first.inner_text())

    browser.close()

print("\n--- 页面错误 ---")
print("\n".join(errors) if errors else "无")
sys.exit(1 if errors else 0)
