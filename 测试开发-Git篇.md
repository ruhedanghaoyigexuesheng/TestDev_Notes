# 测试开发-Git篇

> 对应清单：Git【必须掌握】全部
> 对应自查：Q5（reset 和 revert 的区别；误提交了含密码的代码怎么办）
> 立场：Git 对测开不是"会 pull/push 就行"。**自动化脚本是团队共享资产，它的历史要能追溯、回滚要安全、密钥不能进库。**

---

## 0. 先定位：测开用 Git 的四个高频场景

| 场景 | 用到的能力 |
| --- | --- |
| 想回退一次错误的提交 | `reset` / `revert` / `reflog` |
| 定位"这行代码谁什么时候改的" | `blame` / `log -S` |
| 多人协作提 MR | 分支、合并、冲突解决 |
| 防止密钥/日志进库 | `.gitignore` + 历史清理 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 分支/提交/合并/冲突 | 熟练 | 每天 |
| `reset` 三种模式 + `revert` | 熟练 | 回滚安全的关键 |
| `reflog` | 会用 | 救命用 |
| `log` / `diff` / `blame` | 熟练 | 追溯 |
| 密钥泄露处理 | 知道完整流程 | 面试常问，实战救命 |

---

## 1. 分支、提交、合并、冲突

### 1.1 最小工作流

```bash
git switch -c feature/order-idempotent      # 建功能分支（新版用 switch，checkout 也能用）
git add tests/test_order.py
git commit -m "test(order): 补充下单幂等并发用例"
git push -u origin feature/order-idempotent # 首次推送并建立追踪
# → 提 PR/MR → review → 合并
```

### 1.2 合并方式：merge vs rebase（测试代码库的影响）

| | `merge` | `rebase` |
| --- | --- | --- |
| 历史 | 保留分叉，有 merge commit | 线性，干净 |
| 冲突 | 一次性解决一次 | **每个提交都可能冲突，要逐个解决** |
| 公共分支 | ✅ 用 merge | ❌ 不要对已推送的公共分支 rebase（会改写别人的历史） |
| 个人分支 | 也行 | ✅ 推荐，提交历史更清楚 |

**测开的实际建议**：功能分支合并前 `git rebase origin/main` 保持线性，然后在 MR 里合并；**永远不要 rebase 已经推给别人用的分支**。

### 1.3 解决冲突

```bash
git merge origin/main
# CONFLICT (content): Merge conflict in tests/conftest.py

git status                      # 看哪些文件冲突
# 打开文件，会看到：
# <<<<<<< HEAD
# BASE = "http://test.example.com"
# =======
# BASE = "http://dev.example.com"
# >>>>>>> origin/main

# 手工改成想要的结果后：
git add tests/conftest.py
git commit                      # 完成 merge
# 如果是 rebase 冲突：
git rebase --continue
```

**冲突处理原则**：**冲突不是"选一边"，是"想清楚两边为什么改"。** 测试代码里最常见的冲突是"环境地址"和"依赖版本"，这两类处理方式完全不同：

| 冲突点 | 处理 |
| --- | --- |
| 环境地址 | 大概率应该走配置（配置分离的收益就是消灭这类冲突） |
| 依赖版本 | 取更新的 + 双方都要的，别直接舍弃一边 |
| 断言期望值 | 必须两个人对一下业务规则，不能靠猜 |

**放弃这次合并**：`git merge --abort` / `git rebase --abort`。这是排障的第一步，很多人不知道。

---

## 2. 回滚：`reset` 和 `revert`（自查 Q5 前半）

### 2.1 一句话区别

> **`reset` 是"把分支指针挪回去"，历史被改写；`revert` 是"做一次反向提交"，历史保留、追加。**

### 2.2 三种 `reset` 模式

```bash
git reset --soft HEAD~1     # 撤销提交，改动留在【暂存区】（想重新提交时用）
git reset --mixed HEAD~1    # 撤销提交和暂存，改动留在【工作区】（默认，最常用）
git reset --hard HEAD~1     # 撤销提交，改动【全部丢弃】（危险！）
```

| 模式 | 提交 | 暂存区 | 工作区 | 场景 |
| --- | --- | --- | --- | --- |
| `--soft` | 撤销 | 保留 | 保留 | 提交信息写错了，想重新 commit |
| `--mixed`（默认） | 撤销 | 清空 | 保留 | 想拆成多个提交 / 换个方式提交 |
| `--hard` | 撤销 | 清空 | **丢弃** | 彻底不要这些改动（**先确认没有未提交的工作**） |

**`--hard` 的危险**：工作区的未提交改动会**永久丢失**（除非用 `reflog` 找回提交，但未提交的改动找不回）。执行前先 `git stash` 或 `git status` 确认。

### 2.3 `revert`：安全回滚已推送的提交

```bash
git revert <commit>                   # 生成一个反向提交，抵消那次改动
git revert -n <commit1> <commit2>     # 多个一起 revert，不自动提交
git revert -m 1 <merge-commit>        # 回滚一个 merge commit（-m 1 表示保留第一父分支）
```

**为什么公共分支必须用 revert**：

```
同事已经 pull 了你的提交并基于它开发
你用 reset 把历史改写 + 强推
→ 同事本地历史和远端分叉，下次 pull 全乱
→ 更糟的是 CI/制品库里的构建记录对不上代码
```

### 2.4 决策表（记住这张表就不会用错）

| 情况 | 用什么 |
| --- | --- |
| 只在本地，还没 push | `reset`（`--soft`/`--mixed` 优先，少用 `--hard`） |
| 已 push，分支是共享的（main/develop） | **`revert`** |
| 已 push，但那是你自己的临时分支 | 可以 `reset` + `git push --force-with-lease` |
| 只想撤销某个文件 | `git checkout -- file` / `git restore file` |
| 撤销后想再撤销（恢复回来） | `git reset --hard <reflog 里的 hash>` |

**`--force` vs `--force-with-lease`**：后者会在远端有你没拉取的提交时拒绝推送，是安全版本。**养成只用 `--force-with-lease` 的习惯。**

### 2.5 `reflog`：误操作的救命稻草

```bash
git reflog                    # 所有 HEAD 移动记录（本地，保留 90 天）
git reset --hard HEAD@{3}     # 回到某个历史状态
```

`reflog` 记录的是**本地操作历史**，reset 掉的东西只要没被 gc 就能找回。**误 `reset --hard` 后第一件事就是 `git reflog`，别慌着重新写代码。**

---

## 3. 查看历史：`log`、`diff`、`blame`

### 3.1 `log`：看提交历史

```bash
git log --oneline -20                        # 简洁
git log --oneline --graph --all              # 分支图
git log -p tests/test_order.py               # 这个文件的每次改动内容
git log --author="张三" --since="2026-10-01"  # 按人和时间
git log --grep="幂等"                         # 按提交信息搜
git log -S "O-GEN-" --oneline                # ★ 搜"哪次提交引入/删除了这个字符串"
```

**`git log -S`（pickaxe）是测开的神器**：想知道"这个关掉的开关是哪次提交删的""这个测试账号是什么时候写死的" —— `-S` 一搜就出来。比翻几百个 commit 快得多。

### 3.2 `diff`：看改了什么

```bash
git diff                        # 工作区 vs 暂存区
git diff --staged               # 暂存区 vs 最后一次提交
git diff HEAD~1                 # 最新提交改了什么
git diff --stat                 # 只看改了哪些文件、多少行
git diff main...feature/x       # 分支间差异（PR 里看到的就是这个）
git diff -- tests/conftest.py   # 只看某个文件
```

### 3.3 `blame`：定位"这行是谁什么时候改的"

```bash
git blame tests/conftest.py
git blame -L 20,40 tests/conftest.py      # 只看 20-40 行
git blame -w -C tests/conftest.py         # -w 忽略空白改动，-C 跨文件追踪复制
```

**注意**：`blame` 给的是"最后一次改这行的人"，不一定是"引入问题的人"。**正确用法是配合 `log -p -L` 追历史**：

```bash
git log -L 20,40:tests/conftest.py        # 这 20-40 行的完整变更历史（谁改的、改了几次）
```

这条命令比 blame 更有用，因为它能看到"这行被改过的每一次"，而不是只看到最后一次。

---

## 4. 团队协作流程：feature → PR → review → 合并

```
main（保护分支，不允许直接 push）
  │
  ├─ feature/xxx ──→ push ──→ 开 PR ──→ CI 跑起来 ──→ review ──→ merge
  │                                                      │
  └──────────────────────────────────────────────────────┘
```

### 4.1 一个健康的 PR 应该包含什么

| 内容 | 为什么 |
| --- | --- |
| 改动范围小 | 300 行以内能认真 review，1000 行只能扫一眼"看起来没问题" |
| 描述写清"为什么改" | 不是"改了什么"（diff 自己会说），而是动机和影响 |
| 关联用例/缺陷号 | 可追溯 |
| CI 通过 | 别让人 review 一个跑不过的 PR |
| 自己先看一遍 diff | 最常见的低级错误都是自己 review 能发现的 |

### 4.2 测试代码 review 要抓的五点

1. 断言是不是真的能失败（有没有 `assert True`、`try/except pass`）。
2. 有没有硬编码环境地址、账号。
3. 用例能不能重复执行（幂等、清理是否完整）。
4. 失败信息够不够（能不能一眼看出问题）。
5. 有没有影响别人（改了公共 fixture 会不会拖慢全量）。

### 4.3 常用救援命令

```bash
git stash                     # 临时收起当前改动（切分支前）
git stash pop                 # 恢复
git cherry-pick <commit>      # 把某个提交摘到当前分支（修复要同步到 release 分支时）
git checkout HEAD -- file     # 撤销某个文件的修改
git clean -fd                 # 删除未跟踪的文件（危险，先 -n 预览）
```

---

## 5. `.gitignore`：哪些东西绝对不能进仓库

```gitignore
# 密钥与配置（最重要的三类）
.env
*.local.yaml
config/secrets.yaml
*.pem
*.key
credentials.json

# 测试产物
logs/
artifacts/
reports/
screenshots/
*.log

# 缓存
.pytest_cache/
__pycache__/
*.pyc
.ruff_cache/
.coverage
htmlcov/

# IDE / 系统
.idea/
.vscode/
.DS_Store

# 依赖目录（根据团队约定，一般不提交）
node_modules/
.venv/
venv/
```

**最容易漏的三项**：

| 漏项 | 后果 |
| --- | --- |
| `artifacts/`（失败落盘的请求响应） | 里面可能包含**真实 token、手机号**，一旦提交就是数据泄露 |
| `*.log` | 日志里有数据库密码、用户信息 |
| `.env` / `*.local.yaml` | 环境密码 |

**养成习惯**：`git add` 之后**先 `git status` 和 `git diff --staged` 看一眼再 commit**，尤其是用 `git add .` 的时候。

---

## 6. 自查 Q5 完整作答

### Q5. `git reset` 和 `git revert` 的区别？误提交了含密码的代码怎么办？

#### 第一部分：reset vs revert

> **`reset` 是移动分支指针，改写历史**：`git reset --hard HEAD~1` 之后，那次提交就像没发生过，本地历史里查不到（还能靠 `reflog` 找回），但**如果已经 push，必须强推，会破坏别人的本地历史**。
> **`revert` 是新增一个反向提交来抵消之前的改动**：历史保留，前面那次提交还在，只是在它后面多了一条"撤销它"的提交。
>
> **选择标准只有一条：这个分支有没有别人在用。**
> - 本地没 push → 用 `reset`，干净。
> - 已经 push 到共享分支（main/develop，或别人已经 pull 过）→ **必须用 `revert`**，因为 reset + 强推会让所有人的本地历史和远端分叉。
> - 自己的临时分支 → `reset --hard` + `push --force-with-lease` 也可以。
>
> 补充：`reset` 有三种模式，`--soft` 留暂存区、`--mixed` 留工作区、`--hard` 全丢。日常最常用 `--mixed`（改提交方式），`--hard` 要确认没有未保存的改动再用。

#### 第二部分：误提交密码 —— 这是流程题，不是命令题

**关键认知：改历史不等于消除泄露。** 历史可能已经被别人 clone、被 CI 缓存、被制品库留存、被公开 fork。所以顺序必须是：

```
第一步：立刻吊销     第二步：改历史      第三步：强推 + 通知
（止损）             （清理）            （收尾）
```

**第一步：先让这个密码失效（最重要，也最容易被跳过）**

| 泄露的是什么 | 立刻做什么 |
| --- | --- |
| 数据库密码 | 改数据库密码，重启服务 |
| 云厂商 AccessKey | 到控制台**禁用并轮换**，查有没有异常调用 |
| 第三方 API Key | 吊销重新生成 |
| token/证书 | 吊销证书、重置 token |

**为什么必须先做这一步**：改历史要花时间，而爬虫扫 GitHub 是分钟级的。曾经有团队"先整理历史"，结果密钥在整理期间被用来挖矿。

**第二步：从历史中彻底清除**

`git revert` 只能"再提交一次删除动作"，**旧提交里的密码还在历史里**（`git log -p` 依然能看到）。所以要用历史重写工具：

```bash
# 方案 A：git filter-repo（官方推荐，比 filter-branch 快且不易出错）
pip install git-filter-repo

# 删掉整个文件的历史
git filter-repo --path config/secrets.yaml --invert-paths

# 或者替换文件里的敏感字符串（更精细）
echo "db_password==>***REMOVED***" > expressions.txt
git filter-repo --replace-text expressions.txt

# 方案 B：BFG（Java 工具，速度快）
java -jar bfg.jar --delete-files secrets.yaml
java -jar bfg.jar --replace-text passwords.txt
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

**第三步：强推 + 通知所有人**

```bash
git push --force-with-lease           # 所有分支都要推
git push --force-with-lease --tags
```

然后必须做两件事（不做等于没完成）：

1. **通知所有协作者重新 clone**（或 `git fetch && git reset --hard origin/main`），因为历史被改写了，他们本地的旧历史会导致下次 push 冲突或把旧密码又推回去。
2. **检查 CI/CD 的缓存、制品、日志**里有没有残留。**CI 日志里打印过密码的话，也是泄露面。**

**如果推到过公开仓库**：直接假设已泄露，走第一步吊销，不要指望"删掉就没事"。GitHub 上的提交会被搜索引擎、代码扫描工具、fork 长期留存。

#### 完整话术

> `reset` 改写历史、只能用于本地；`revert` 追加反向提交、用于已推送的共享分支。
> 误提交密码，我按三步走：**先吊销密码**（因为泄露是按分钟算的，改历史要时间）；**再改历史**（`git filter-repo` 或 BFG，因为 `revert` 只是删除动作，旧提交里的密码还在）；**最后强推并通知所有人重新 clone**，同时清理 CI 缓存和日志残留。
> 根本预防是两点：`.gitignore` 提前排除 `.env`、`secrets.yaml`、`artifacts/`；用 `detect-private-key` 这类 pre-commit hook 在提交时拦截。

---

## 7. 动手清单

- [ ] 在一个测试仓库里跑 `git log -S "某个硬编码的地址"`，看是哪次提交引入的。
- [ ] 用 `git log -L` 看某个 fixture 的完整变更历史，比 blame 更有信息量。
- [ ] 检查你们的 `.gitignore` 有没有 `artifacts/`、`*.log`、`.env`（失败落盘文件最容易漏）。
- [ ] 演练一次"误提交 → revert → 找回"（用 reflog），形成肌肉记忆。
