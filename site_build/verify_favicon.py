import base64
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(r"D:\Doc\TestDev_Route")
HTML = ROOT / "测试开发知识库.html"
OUT = ROOT / "site_build"
URL = "file:///" + quote(str(HTML).replace("\\", "/"))

src = HTML.read_text(encoding="utf-8")
m = re.search(r'data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)', src)
svg = base64.b64decode(m.group(1)).decode("utf-8")

# 预览页：三种尺寸 + 深浅底色，模拟标签栏效果
preview = OUT / "_favicon_preview.html"
preview.write_text(f"""<!doctype html><meta charset="utf-8">
<style>
body{{margin:0;font-family:system-ui;background:#eee;padding:24px}}
.row{{display:flex;gap:28px;align-items:flex-end;margin-bottom:24px}}
.cell{{text-align:center;font-size:11px;color:#666}}
.light{{background:#fff;padding:14px;border-radius:10px;display:inline-grid;place-items:center}}
.dark{{background:#202124;padding:14px;border-radius:10px;display:inline-grid;place-items:center}}
</style>
<div class="row">
  <div class="cell"><div class="light"><img src="data:image/svg+xml;base64,{m.group(1)}" width="128" height="128"></div><br>128px</div>
  <div class="cell"><div class="light"><img src="data:image/svg+xml;base64,{m.group(1)}" width="48" height="48"></div><br>48px</div>
  <div class="cell"><div class="light"><img src="data:image/svg+xml;base64,{m.group(1)}" width="32" height="32"></div><br>32px</div>
  <div class="cell"><div class="light"><img src="data:image/svg+xml;base64,{m.group(1)}" width="16" height="16"></div><br>16px</div>
  <div class="cell"><div class="dark"><img src="data:image/svg+xml;base64,{m.group(1)}" width="32" height="32"></div><br>深色 32px</div>
</div>""", encoding="utf-8")

problems = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 760, "height": 300}, device_scale_factor=2)

    page.goto("file:///" + quote(str(preview).replace("\\", "/")), wait_until="load")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "favicon_preview.png"))
    print("图标预览已生成")

    # 确认主页面里的 favicon 声明
    page.goto(URL, wait_until="load")
    page.wait_for_timeout(500)
    info = page.evaluate("""() => {
        const l = document.querySelector('link[rel="icon"]');
        return l ? {rel: l.rel, type: l.type, len: l.href.length,
                    isData: l.href.startsWith('data:image/svg+xml')} : null;
    }""")
    print("link[rel=icon]:", info)
    if not info or not info.get("isData"):
        problems.append("favicon 未正确绑定")
    if "__FAVICON__" in src:
        problems.append("占位符残留")

    # 页头 logo
    page.screenshot(path=str(OUT / "shot_header.png"), clip={"x": 0, "y": 0, "width": 460, "height": 60})
    print("页头已截图")

    browser.close()

print("\n--- 问题 ---")
print("\n".join(problems) if problems else "无")
