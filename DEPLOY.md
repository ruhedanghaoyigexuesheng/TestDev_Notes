# 部署到 GitHub Pages

免费、自带 HTTPS、不用买服务器。**一次配好，以后 push 一次 Markdown 就自动更新站点。**

> 本文档只覆盖 GitHub Pages。仓库里的 `.github/workflows/pages.yml` 已经写好了，
> 你只需要把代码推上去、在网页上点两下。

---

## 一、准备（只做一次）

### 1. 在 GitHub 上建一个空仓库

- 打开 <https://github.com/new>
- Repository name 填一个英文名，例如 `testdev-notes`（**这个名字会出现在网址里**）
- 选 Public（私有仓库也能用 Pages，但部分账号需要付费套餐）
- **不要**勾选 "Add a README file"（避免和本地冲突）

建完你会得到仓库地址，例如：
```
https://github.com/<你的用户名>/testdev-notes.git
```

### 2. 本地初始化并推送

在 `D:\Doc\TestDev_Route` 目录下依次执行（把 `<用户名>` 和仓库名换成你自己的）：

```bash
cd /d D:\Doc\TestDev_Route

git init
git config core.quotepath false          # 让中文文件名正常显示（可选但推荐）
git add .
git commit -m "docs: 测试开发知识库（32 篇 + 单文件站点）"
git branch -M main

git remote add origin https://github.com/<用户名>/testdev-notes.git
git push -u origin main
```

> 首次 push 会要求登录。推荐用 **Personal Access Token** 当密码：
> GitHub → Settings → Developer settings → Personal access tokens → 勾 `repo` 权限。
>
> 也可以装 GitHub CLI 后 `gh auth login`，更省事。

### 3. 打开 Pages

仓库页面 → **Settings** → 左侧 **Pages**：

- **Source** 选 `GitHub Actions`（不要选 "Deploy from a branch"）

保存即可。**不需要手动选分支**，因为仓库里已经有 `.github/workflows/pages.yml`，
它会自动从 32 篇 Markdown 重新生成 HTML 并发布。

### 4. 等第一次构建完成

- 打开仓库的 **Actions** 标签页，能看到一条 `Deploy to GitHub Pages` 在跑
- 约 1~2 分钟跑完（构建只需几秒，主要时间在排队）
- 完成后在 **Settings → Pages** 顶部会显示站点地址：

```
https://<用户名>.github.io/testdev-notes/
```

打开就是和本地一模一样的知识库（搜索、目录、代码高亮全都在）。

---

## 二、以后怎么更新

改完任意 `.md`（或者新增一篇），只要：

```bash
git add .
git commit -m "docs: 补充 xxx 篇"
git push
```

push 触发的 workflow 会自动：
1. checkout 代码
2. `python site_build/build_site.py --out dist/index.html` 重新生成站点
3. 部署到 Pages

**你不需要在本地跑构建脚本**，也不需要手动上传 HTML。

如果只想手动触发一次部署：Actions 页面 → 选中 `Deploy to GitHub Pages` → **Run workflow**。

---

## 三、这个 workflow 做了什么

`.github/workflows/pages.yml` 两个 job：

| job | 内容 |
| --- | --- |
| **build** | 装 Python 3.11 → 跑 `build_site.py --out dist/index.html` → 校验产物非空 → 上传静态文件 |
| **deploy** | 用官方 `actions/deploy-pages` 发布到 Pages |

关键配置：

- `permissions: pages: write + id-token: write`：Pages 部署必需
- `concurrency: group: pages`：避免两次部署打架
- `paths` 过滤：只有改到 `**.md`、`site_build/**` 或 workflow 本身才触发，改 README 之外的东西不会空跑

> 构建脚本只依赖 Python 标准库（`json`/`re`/`pathlib`/`base64`），
> 所以 CI 里**不用 pip install 任何东西**，构建通常 2~3 秒。

---

## 五、方案 B：不用 Actions 的最简做法

如果你不想折腾 CI，也可以纯手动（**适合偶尔更新一次**）：

1. 本地生成站点，并放到仓库根目录，命名为 `index.html`：

   ```bash
   python site_build/build_site.py --out index.html
   ```

2. push 上去
3. 仓库 **Settings → Pages → Source** 选 `Deploy from a branch`，
   Branch 选 `main`，目录选 `/ (root)`
4. 等 1 分钟，访问 `https://<用户名>.github.io/<仓库名>/`

**和方案 A 的区别**：

| | 方案 A（Actions） | 方案 B（分支） |
| --- | --- | --- |
| 改完 md 后 | push 即自动更新 | **要记得本地重新生成 index.html 再 push** |
| 仓库里存什么 | md + 构建脚本 | 还要多存一份 index.html |
| 首次配置 | 需选 `GitHub Actions` | 需选分支和目录 |
| 适合 | 会持续更新内容 | 只发一次、不打算再改 |

> 两种可以并存：仓库里同时提交 `index.html` 和 workflow，
> 平时走 Actions，万一 CI 出问题可以临时切回分支部署。

---

## 六、常见问题

| 问题 | 说明 / 处理 |
| --- | --- |
| **网址里带仓库名，能去掉吗** | 把仓库命名为 `<用户名>.github.io`，站点就是 `https://<用户名>.github.io/`（一个账号只有一个这种根站点） |
| **中文文件名会不会出问题** | 不会。GitHub 支持，站点里已内嵌全部内容，不依赖文件名加载 |
| **`git status` 里中文变乱码** | `git config core.quotepath false` |
| **国内访问 `github.io` 慢/打不开** | 常见现象。可以换 Cloudflare Pages / Vercel / Netlify（都是免费静态托管，国内相对稳定），构建命令填 `python site_build/build_site.py --out dist/index.html`，输出目录填 `dist` |
| **想用私有仓库** | 私有仓库的 Pages 站点**仍然是公开可访问**的；如果 md 内容不想公开，注意这一点 |
| **仓库变大了** | 每次改 md 都会提交一份 ~0.8MB 的 HTML。文本压缩率高，几十次提交也才几十 MB，不用管；实在介意就把 `测试开发知识库.html` 加进 `.gitignore`，只保留 CI 构建产物 |
| **Actions 报 `Permission denied`** | 检查 Settings → Actions → General → Workflow permissions 是否为 Read and write，以及 Pages 的 Source 是否选了 `GitHub Actions` |

---

## 五、本地预览

```bash
# 生成到 dist/index.html
python site_build/build_site.py --out dist/index.html

# 直接双击本地 HTML（零依赖，不需要服务器）
start dist\index.html
```

不需要 `python -m http.server`——它是单文件，`file://` 打开功能完整。
