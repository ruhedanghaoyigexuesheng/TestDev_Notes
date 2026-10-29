"""对线上 GitHub Pages 站点做一次真实浏览器验收。"""
import sys

from playwright.sync_api import sync_playwright

SITE = "https://ruhedanghaoyigexuesheng.github.io/TestDev_Notes/"
PROXY = {"server": "http://127.0.0.1:33210"}

problems = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", proxy=PROXY)
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)

    # 1. 首页
    page.goto(SITE, wait_until="load", timeout=60000)
    page.wait_for_timeout(1200)
    title = page.title()
    nav = page.locator(".nav-item").count()
    cards = page.locator(".card").count()
    stats = page.locator(".stat .n").all_inner_texts()
    favicon = page.evaluate(
        "() => { const l = document.querySelector('link[rel=icon]'); "
        "return l ? l.href.slice(0, 40) : null; }")
    print(f"title      : {title}")
    print(f"导航项/卡片 : {nav} / {cards}")
    print(f"统计数字    : {stats}")
    print(f"favicon    : {favicon}")
    if nav != 33:
        problems.append(f"导航项数异常 {nav}")
    if cards != 33:
        problems.append(f"卡片数异常 {cards}")

    # 2. 文章路由 + 渲染
    for aid, expect in [("net", "计算机网络篇"), ("mysql", "MySQL篇"),
                        ("ai-eval", "AI应用评测篇")]:
        page.goto(SITE + "#/" + aid, wait_until="load")
        page.wait_for_timeout(900)
        t = page.title()
        codes = page.locator(".code-wrap").count()
        toks = page.locator(".tok-k").count()
        tables = page.locator(".doc-body table").count()
        toc = page.locator("#tocList a").count()
        print(f"  #{aid:<8} title={t[:28]:<28} 代码块={codes:<3} token={toks:<4} 表格={tables:<3} 目录={toc}")
        if expect not in t:
            problems.append(f"{aid} 标题不符: {t}")
        if codes == 0 or toks == 0:
            problems.append(f"{aid} 代码块/高亮异常")

    # 3. 搜索
    page.goto(SITE, wait_until="load")
    page.wait_for_timeout(600)
    page.fill("#searchInput", "幂等")
    page.wait_for_timeout(800)
    hits = page.locator(".sr-item").count()
    print(f"  搜索『幂等』命中: {hits} 条")
    if hits == 0:
        problems.append("线上搜索无结果")

    # 4. 站内链接改写（README 里的篇目链接）
    page.goto(SITE + "#/readme", wait_until="load")
    page.wait_for_timeout(800)
    hrefs = page.eval_on_selector_all(".doc-body a", "els => els.map(e => e.getAttribute('href'))")
    md_links = [h for h in hrefs if h and h.endswith(".md")]
    print(f"  README 内 .md 链接残留: {len(md_links)}")
    if md_links:
        problems.append(f"仍有 md 直链: {md_links[:3]}")

    # 5. 复制按钮
    page.goto(SITE + "#/git", wait_until="load")
    page.wait_for_timeout(700)
    page.locator(".copy-btn").first.click()
    page.wait_for_timeout(300)
    label = page.locator(".copy-btn").first.inner_text()
    print(f"  复制按钮反馈: {label}")

    page.screenshot(path="shot_live.png")
    browser.close()

print("\n--- 问题 ---")
print("\n".join(problems) if problems else "无")
sys.exit(1 if problems else 0)
