import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(r"D:\Doc\TestDev_Route")
HTML = ROOT / "测试开发知识库.html"
OUT = ROOT / "site_build"
URL = "file:///" + quote(str(HTML).replace("\\", "/"))

problems = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))

    page.goto(URL, wait_until="load")
    page.wait_for_timeout(600)

    tags = page.locator(".nav-item .tag").all_inner_texts()
    print("导航编号:", tags)
    bad = [t for t in tags if not t.strip().isdigit()]
    if bad:
        problems.append(f"非法编号: {bad}")

    # 文章页 meta
    page.goto(URL + "#/net", wait_until="load")
    page.wait_for_timeout(500)
    meta = page.locator(".doc-meta .pill").all_inner_texts()
    print("文章元信息:", meta)
    if any("NaN" in m for m in meta):
        problems.append("meta 出现 NaN")

    # 全文扫一遍：渲染所有文章，检查侧边栏与正文有无 NaN
    page.screenshot(path=str(OUT / "shot_home.png"))
    page.goto(URL + "#/api-design", wait_until="load")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "shot_article.png"))

    ids = page.evaluate("Array.from(document.querySelectorAll('.nav-item')).map(e=>e.dataset.id)")
    bad_pages = []
    for aid in ids:
        page.goto(URL + "#/" + aid, wait_until="load")
        body = page.locator("#view").inner_text()
        if "NaN" in body:
            bad_pages.append(aid)
    print(f"检查 {len(ids)} 篇，含 NaN 的页面: {bad_pages or '无'}")
    if bad_pages:
        problems.append(f"页面含 NaN: {bad_pages}")

    browser.close()

print("\n--- 问题 ---")
print("\n".join(problems) if problems else "无")
sys.exit(1 if problems else 0)
