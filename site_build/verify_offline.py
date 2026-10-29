"""验证单文件 HTML 是否真的离线自包含：断网加载 + 监控所有网络请求。"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(r"D:\Doc\TestDev_Route")
HTML = ROOT / "测试开发知识库.html"
URL = "file:///" + quote(str(HTML).replace("\\", "/"))
src = HTML.read_text(encoding="utf-8")

problems = []

# ---------- 1. 静态扫描：有没有外部资源引用 ----------
print("=== 静态扫描 ===")
checks = {
    "<script src=": re.findall(r"<script[^>]+src=", src),
    "<link href=http": re.findall(r'<link[^>]+href="https?://', src),
    "<img src=http": re.findall(r'<img[^>]+src="https?://', src),
    "@import": re.findall(r"@import", src),
    "@font-face": re.findall(r"@font-face", src),
    "css url(http": re.findall(r"url\(\s*['\"]?https?://", src),
}
for k, v in checks.items():
    print(f"  {k:16} {len(v)}")
    if v:
        problems.append(f"存在外部引用: {k} x{len(v)}")

links = re.findall(r"<link[^>]*>", src)
print(f"  全部 <link> 标签 {len(links)} 个：")
for l in links:
    kind = "favicon(data)" if "data:image" in l else l[:60]
    print("    -", kind)

# 正文里的外链（超链接不算资源依赖，仅统计）
anchors = re.findall(r'<a[^>]+href="(https?://[^"]+)"', src)
print(f"  正文外链（可点开的超链接，不影响离线）: {len(anchors)} 个")

# ---------- 2. 断网加载 ----------
print("\n=== 断网加载 ===")
external_requests = []
failed = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    page = ctx.new_page()

    def on_req(req):
        if req.url.startswith("http://") or req.url.startswith("https://"):
            external_requests.append(req.url)

    page.on("request", on_req)
    page.on("requestfailed", lambda r: failed.append(f"{r.url} :: {r.failure}"))
    page.on("pageerror", lambda e: failed.append(f"pageerror: {e}"))

    ctx.set_offline(True)          # 彻底断网
    page.goto(URL, wait_until="load")
    page.wait_for_timeout(800)

    nav = page.locator(".nav-item").count()
    cards = page.locator(".card").count()
    print(f"  导航项 {nav} / 卡片 {cards}")

    page.goto(URL + "#/mysql", wait_until="load")
    page.wait_for_timeout(700)
    codes = page.locator(".code-wrap").count()
    hl = page.locator(".tok-k").count()
    tables = page.locator(".doc-body table").count()
    print(f"  代码块 {codes} / 高亮 token {hl} / 表格 {tables}")

    page.goto(URL, wait_until="load")
    page.wait_for_timeout(400)
    page.fill("#searchInput", "幂等")
    page.wait_for_timeout(600)
    hits = page.locator(".sr-item").count()
    print(f"  离线搜索命中 {hits} 条")

    page.goto(URL + "#/readme", wait_until="load")
    page.wait_for_timeout(500)
    page.locator('.doc-body a', has_text="测试开发-操作系统篇").first.click()
    page.wait_for_timeout(500)
    print(f"  离线点击跳转: {page.evaluate('location.hash')} / {page.title()}")

    ctx.set_offline(False)
    browser.close()

print(f"\n  外部网络请求: {len(external_requests)} 个 {external_requests[:3]}")
print(f"  失败请求/错误: {len(failed)} 个 {failed[:3]}")
if external_requests:
    problems.append("存在外部网络请求")
if failed:
    problems.append("存在失败请求")

print("\n--- 结论 ---")
print("✅ 完全自包含，可直接分发单个 HTML" if not problems else "❌ " + " | ".join(problems))
sys.exit(1 if problems else 0)
