# 站点构建说明

产物：仓库根目录的 **`测试开发知识库.html`**（单文件、零依赖，双击即可用浏览器打开）。

## 重新生成

改完任意 `.md` 后，在本目录执行：

```bash
python build_site.py                  # 输出到 ../测试开发知识库.html
python build_site.py --out dist/index.html   # 指定输出路径（CI 部署用这个）
```

会重新读取 32 篇 Markdown + README，生成新的 HTML。

> 部署到 GitHub Pages 见根目录的 [DEPLOY.md](../DEPLOY.md)，
> Actions 会自动执行 `python site_build/build_site.py --out dist/index.html`。

## 文件职责

| 文件 | 作用 |
| --- | --- |
| `build_site.py` | 读取 md → 生成数据 → 注入模板 → 输出单文件 HTML |
| `template.html` | 页面骨架（样式 + 交互逻辑），含两个占位符 `__KB_DATA__` / `__RENDER_CORE__` |
| `render_core.js` | Markdown 渲染 + 语法高亮内核（纯函数，无 DOM 依赖） |
| `test_render.js` | 渲染内核单元测试：`node test_render.js` |
| `verify_site.js` | 成品校验（占位符残留、JS 语法、33 篇渲染、内容抽样）：`node verify_site.js` |

## 校验

```bash
node test_render.js    # 渲染内核（26 项）
node verify_site.js    # 成品站点（16 项）
```

两项都应输出 `ALL PASS`。

## 常见改动

- **新增一篇笔记**：在 `build_site.py` 的 `GROUPS` 里加一条 `(id, 标题, 摘要)`，
  并把 `测试开发-<标题>.md` 放进根目录，重新生成即可。
- **调代码块配色**：`template.html` 里搜 `.tok-` 与 `.code-bg`。
- **改主题色**：`template.html` 顶部 `:root` 的 `--brand` / `--accent`。
