"""验证 md 内部链接已改写成站内路由（点击不会跳出 HTML）。"""
import re
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

    # 进"使用说明与索引"（README），检查里面所有 .md 链接
    page.goto(URL + "#/readme", wait_until="load")
    page.wait_for_timeout(600)

    hrefs = page.eval_on_selector_all(
        ".doc-body a", "els => els.map(e => e.getAttribute('href'))")
    md_links = [h for h in hrefs if h and h.endswith('.md')]
    print(f"正文链接 {len(hrefs)} 个，其中仍指向 .md 的: {md_links}")
    if md_links:
        problems.append(f"未改写的 md 链接: {md_links[:5]}")

    route_links = [h for h in hrefs if h and h.startswith('#/')]
    print(f"已改写为站内路由: {len(route_links)} 个，示例: {route_links[:3]}")
    if len(route_links) < 30:
        problems.append(f"站内路由链接偏少: {len(route_links)}")

    # 真实点击表格里的「测试开发-操作系统篇」
    link = page.locator('.doc-body a', has_text="测试开发-操作系统篇").first
    if link.count() == 0:
        problems.append("找不到目标链接")
    else:
        link.click()
        page.wait_for_timeout(700)
        print("点击后 URL hash:", page.evaluate("location.hash"))
        print("点击后标题:", page.title())
        if "#/os" not in page.evaluate("location.hash"):
            problems.append("点击未跳转到站内路由 #/os")
        if "操作系统篇" not in page.title():
            problems.append("点击后标题不正确")
        if "file:///" in page.url and not page.url.endswith(".html#/os"):
            problems.append(f"跳出了 HTML: {page.url}")

    # 再点几篇，确认都可路由
    for name, expect_id in [("测试开发-MySQL篇", "mysql"), ("测试开发-AI应用评测篇", "ai-eval")]:
        page.goto(URL + "#/readme", wait_until="load")
        page.wait_for_timeout(350)
        page.locator('.doc-body a', has_text=name).first.click()
        page.wait_for_timeout(500)
        h = page.evaluate("location.hash")
        if "#/" + expect_id not in h:
            problems.append(f"{name} 跳转异常: {h}")
        else:
            print(f"{name} -> {h} ✓")

    page.screenshot(path=str(OUT / "shot_readme.png"))
    browser.close()

print("\n--- 问题 ---")
print("\n".join(problems) if problems else "无")
sys.exit(1 if problems else 0)
