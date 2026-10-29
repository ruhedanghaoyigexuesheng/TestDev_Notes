# -*- coding: utf-8 -*-
"""把 32 篇 Markdown 打包成单文件 HTML 导航站（双击即可打开，无需服务器）。"""
import base64
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(__file__).resolve().parent
OUT = ROOT / "测试开发知识库.html"

# ---------------------------------------------------------------- 站点图标
# 「QA」字母标：几何笔画手绘（不依赖系统字体，跨平台渲染一致）
# 排版基准：Q 的圆环外径 = A 的「顶点→腿底」高度 + 笔画宽，两者墨迹等高
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#4ea47a"/><stop offset="1" stop-color="#2a6a4a"/>'
    '</linearGradient></defs>'
    '<rect width="64" height="64" rx="14" fill="url(#g)"/>'
    # Q：圆环外径 24 = A 的主体高 19 + 笔画 5，两者墨迹等高
    '<circle cx="19" cy="32" r="9.5" fill="none" stroke="#ffffff" stroke-width="5"/>'
    '<path d="M25.7 38.7 29 42" stroke="#ffffff" stroke-width="5" stroke-linecap="round"/>'
    # A：主体高 19、底宽 17，横杠落在视觉重心（y=36），加长到与底宽协调
    '<path d="M45 22 36.5 41M45 22 53.5 41M38.7 36H51.3" fill="none" stroke="#ffffff" '
    'stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
FAVICON_URI = "data:image/svg+xml;base64," + base64.b64encode(
    FAVICON_SVG.encode("utf-8")).decode("ascii")

# ---------------------------------------------------------------- 分组与摘要
GROUPS = [
    ("一、计算机基础", [
        ("net", "计算机网络篇", "HTTP/TCP/DNS/会话机制/状态码/URL 到渲染"),
        ("os", "操作系统篇", "进程线程/IPC/死锁/内存管理/I/O 模型"),
        ("algo", "数据结构与算法篇", "七种结构、四道手写题、复杂度实战"),
        ("sysdesign", "系统设计意识篇", "缓存/限流/超时/重试/熔断/降级/幂等"),
    ]),
    ("二、语言与框架（Python）", [
        ("python", "Python语言核心篇", "异常处理/OOP封装/集合选型/文件读写/requests/并发"),
        ("pytest", "pytest框架篇", "fixture/参数化/mark/conftest+hook/插件/Mock"),
        ("practice", "工程习惯篇", "日志/配置分离/防假绿/lint/自建靶子服务"),
    ]),
    ("三、数据、中间件与工程运维", [
        ("mysql", "MySQL篇", "SQL/JOIN/事务隔离级别/SQL 断言/EXPLAIN"),
        ("redis", "Redis与缓存篇", "五种结构选型/redis-cli 造数/一致性用例"),
        ("middleware", "中间件篇", "MQ 四要点（到达/重复/乱序/积压）+ Nginx 502/504"),
        ("linux", "Linux命令篇", "查日志（grep/tail/awk/sed）、看状态、网络排查"),
        ("git", "Git篇", "reset vs revert/reflog/blame/密钥泄露处理"),
        ("docker", "Docker与K8s篇", "镜像容器/挂载/compose/一次性干净库/kubectl 四板斧"),
        ("cicd", "CI-CD篇", "流水线三段结构/GitHub Actions/失败定位"),
    ]),
    ("四、测试方法与质量工程", [
        ("process", "测试流程与方法论篇", "流程八环节/测试金字塔/七种类型/越权"),
        ("casedesign", "用例设计方法篇", "八种设计方法/六维框架/文件上传 38 点/状态机"),
        ("defect", "缺陷与质量工程篇", "缺陷单七要素/Severity vs Priority/左移右移"),
    ]),
    ("五、接口测试与自动化", [
        ("api-basic", "接口基础与抓包篇", "OpenAPI 读法/抓包/签名与时间戳/Token"),
        ("api-design", "接口测试设计与断言篇", "单接口清单/链路测试/五层断言/用例幂等"),
        ("api-framework", "接口自动化框架篇", "六组件与目录树/配置分层/Allure/CI 失败定位"),
        ("api-mock", "接口Mock与安全篇", "Mock 三层工具/越权自动化/AI 用例审查"),
    ]),
    ("六、UI 与 App 自动化", [
        ("webui", "WebUI自动化篇", "Playwright 选择器/自动等待/route Mock/Trace"),
        ("app", "App自动化篇", "Appium/Capabilities/权限弹窗/弱网/logcat"),
        ("ui-eng", "UI自动化工程化篇", "POM 三层/失败五件套/登录态复用/flaky 治理"),
    ]),
    ("七、性能测试", [
        ("perf-design", "性能测试设计篇", "五种目标/八步方法论/QPS-TPS/P95-P99/利特尔法则"),
        ("perf-monitor", "性能监控与调优篇", "四层监控/瓶颈证据/慢 SQL 优化/内存泄漏"),
    ]),
    ("八、质量工程与效能", [
        ("pipeline", "质量流水线与门禁篇", "四级流水线/失败通知/左移右移落地"),
        ("platform", "测试平台与质量度量篇", "平台五模块/三类指标与失真/趋势数据"),
        ("coverage", "覆盖率与精准测试篇", "覆盖率边界/增量覆盖率/精准测试脚本"),
    ]),
    ("九、AI 辅助测试", [
        ("ai-assist", "AI辅助测试篇", "提示词四要素/四个模板/CLAUDE.md/MCP 与 Skill"),
    ]),
    ("十、AI 应用评测", [
        ("ai-eval", "AI应用评测篇", "四类应用/Judge 校准/pass@k/非确定性断言"),
        ("ai-ops", "AI应用质量运营篇", "Dify 实操/Golden Set/上线门禁/提示词注入"),
    ]),
]


def read_md(filename: str) -> str:
    p = ROOT / filename
    if not p.exists():
        raise SystemExit(f"缺少文件: {p}")
    return p.read_text(encoding="utf-8")


def strip_fences(content: str) -> str:
    """把代码块内容替换成空行（保留行结构），便于统计块外的表格/字数。"""
    out = []
    depth = 0
    for line in content.split("\n"):
        m = re.match(r"^\s*(`{3,})", line)
        if m:
            if depth == 0:
                depth = len(m.group(1))
                out.append("")
                continue
            if len(m.group(1)) >= depth:
                depth = 0
                out.append("")
                continue
        out.append(line if depth == 0 else "")
    return "\n".join(out)


def count_fence_blocks(content: str) -> int:
    """按状态机数顶层代码块（正确处理 4 反引号包裹 3 反引号的情况）。"""
    blocks = 0
    depth = 0
    for line in content.split("\n"):
        m = re.match(r"^\s*(`{3,})", line)
        if not m:
            continue
        if depth == 0:
            depth = len(m.group(1))
            blocks += 1
        elif len(m.group(1)) >= depth:
            depth = 0
    return blocks


def count_stats(content: str) -> dict:
    plain = strip_fences(content)
    chars = len(re.sub(r"\s", "", plain))
    codes = count_fence_blocks(content)
    # 去掉引用块前缀，让引用内的表格也能被统计到
    plain2 = re.sub(r"^\s*>\s?", "", plain, flags=re.M)
    tables = 0
    for line in plain2.split("\n"):
        if "|" in line and "-" in line and re.fullmatch(r"[\s:|\-]+", line):
            tables += 1
    return {"chars": chars, "codes": codes, "tables": tables}


def build_data() -> dict:
    groups = []
    total_chars = total_codes = total_tables = 0

    # 首页入口（README 作为"使用说明"）
    start_art = {
        "id": "readme",
        "title": "使用说明与索引",
        "desc": "三遍复习法、自查清单映射表、命名与拆分规则",
        "file": "README.md",
        "content": read_md("README.md"),
        **count_stats(read_md("README.md")),
    }
    groups.append({"name": "开始", "articles": [start_art]})

    for gname, items in GROUPS:
        arts = []
        for aid, title, desc in items:
            content = read_md(f"测试开发-{title}.md")
            st = count_stats(content)
            total_chars += st["chars"]
            total_codes += st["codes"]
            total_tables += st["tables"]
            arts.append({
                "id": aid,
                "title": title,
                "desc": desc,
                "file": f"测试开发-{title}.md",
                "content": content,
                "chars": st["chars"],
                "codes": st["codes"],
                "tables": st["tables"],
            })
        groups.append({"name": gname, "articles": arts})

    # 自查题数量从 README 的映射表动态统计
    readme_src = read_md("README.md")
    qa_count = len(re.findall(r"^\|\s*\d+\s*\|", readme_src, re.M))

    stats = [
        {"n": "32", "l": "篇笔记"},
        {"n": f"{round(total_chars / 10000, 1)}", "l": "万字正文"},
        {"n": str(total_codes), "l": "段代码"},
        {"n": str(qa_count), "l": "条自查题"},
    ]
    return {"groups": groups, "stats": stats}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="把 Markdown 打包成单文件 HTML 站点")
    parser.add_argument("--out", default=None,
                        help="输出路径，默认：<仓库根>/测试开发知识库.html")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else OUT
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = build_data()
    template = (BUILD / "template.html").read_text(encoding="utf-8")
    core = (BUILD / "render_core.js").read_text(encoding="utf-8")

    kb_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 防止提前闭合 script 标签 + 规避 json 行分隔符问题
    kb_json = (kb_json
               .replace("</", "<\\/")
               .replace("\u2028", "\\u2028")
               .replace("\u2029", "\\u2029"))

    html = (template
            .replace("__KB_DATA__", kb_json)
            .replace("__RENDER_CORE__", core)
            .replace("__FAVICON__", FAVICON_URI))

    out_path.write_text(html, encoding="utf-8")

    size_mb = out_path.stat().st_size / 1024 / 1024
    arts = sum(len(g["articles"]) for g in data["groups"])
    print(f"✅ 已生成: {out_path}")
    print(f"   篇目 {arts - 1} 篇 + 使用说明 1 篇")
    print(f"   正文 {data['stats'][1]['n']} 万字 | 代码 {data['stats'][2]['n']} 段 | 自查题 {data['stats'][3]['n']} 条")
    print(f"   体积 {size_mb:.2f} MB（单文件，双击即可打开）")


if __name__ == "__main__":
    main()
