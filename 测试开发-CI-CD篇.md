# 测试开发-CI/CD篇

> 对应清单：CI/CD【必须掌握（概念 + 一次实操）】全部
> 对应自查：Q9（描述一条 GitHub Actions 流水线：触发、跑什么、产物在哪、失败怎么通知）
> 立场：这一篇的目标只有一个 —— **让"提交代码 → 自动跑测试 → 出报告"这条链路真的跑起来一次**。跑通过一次，你对 CI 的理解就会超过 90% 只会点"重新运行"的人。

---

## 0. 先定位：CI 在测试工作里的意义

没有 CI 的时候：

```
开发改完 → 群里喊"帮忙回归一下" → 你本地拉代码跑 → 报告发群里 → 漏了没人知道
```

有 CI 之后：

```
开发提 PR → 自动跑测试 → 结果挂在 PR 上 → 红了不许合 → 报告自动归档
```

**关键差别不是"自动化"，是"门禁"**：让"测试没通过"这件事**没法被忽略**。

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 流水线结构（触发/阶段/通知） | 熟练 | 概念题 |
| GitHub Actions 写一条能跑的 | **会一次实操** | 本篇核心 |
| 看日志定位失败 | 熟练 | 值班必用 |
| Jenkins 的对应概念 | 看得懂 | 多数公司在用 |
| 分层跑测试（冒烟/全量/夜间） | 会用 | 决定流水线快不快 |

---

## 1. 流水线的基本结构：三段

```
触发（Trigger）
  ├─ push 到某分支
  ├─ 提 PR / MR
  ├─ 定时（每天凌晨全量）
  └─ 手动（发版前）
       ↓
阶段（Stages）
  ├─ 准备：拉代码、装依赖（缓存）
  ├─ 构建：打包/编译（可选）
  ├─ 测试：单元 → 接口 → UI（按耗时从短到长）
  ├─ 报告：生成 HTML/Allure，上传 artifact
  └─ 归档/发布：推制品、打 tag
       ↓
通知（Notify）
  ├─ 失败通知（IM 群/邮件/@ 人）
  └─ 结果沉淀（报告链接、覆盖率趋势）
```

### 1.1 测试在流水线里的分层（决定流水线快不快）

| 层 | 什么时候跑 | 目标耗时 | 失败怎么办 |
| --- | --- | --- | --- |
| 单元测试 | 每次 push | < 2 分钟 | **阻塞合并** |
| 接口冒烟（`-m smoke`） | 每次 push / PR | < 5 分钟 | **阻塞合并** |
| 接口全量 | 合并到 main / 每晚 | < 30 分钟 | 阻塞发版 |
| UI 自动化 | 每晚 / 发版前 | 1~2 小时 | 阻塞发版 |
| 性能压测 | 每周 / 大版本前 | 按场景 | 出报告评审 |

**核心原则**：**提交级只跑冒烟，全量放到夜间。** 一个 40 分钟的流水线，开发会想办法绕过它（比如把测试标记成 skip），那 CI 就名存实亡了。

---

## 2. GitHub Actions 实操：一条能跑的流水线

### 2.1 文件放哪

```
你的仓库/
├── .github/
│   └── workflows/
│       └── api-tests.yml      ← 就放这里
├── tests/
├── requirements.txt
└── pytest.ini
```

### 2.2 完整配置（可直接用）

```yaml
# .github/workflows/api-tests.yml
name: api-tests

# ── 触发 ────────────────────────────────────────────
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 18 * * *"        # UTC 18:00 = 北京时间次日 02:00，跑夜间全量
  workflow_dispatch:             # 支持手动触发（带参数见下文）

# 同一个分支的旧流水线自动取消，省资源也避免结果混乱
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

# ── 任务 ────────────────────────────────────────────
jobs:
  api-test:
    runs-on: ubuntu-latest
    timeout-minutes: 30          # 兜底：防止卡死占用额度

    # 用容器起依赖，流水线自带干净的 MySQL
    services:
      mysql:
        image: mysql:5.7
        env:
          MYSQL_ROOT_PASSWORD: "123456"
          MYSQL_DATABASE: "qa_shop"
        ports:
          - 3306:3306
        options: >-
          --health-cmd="mysqladmin ping -h 127.0.0.1 -p123456"
          --health-interval=5s
          --health-timeout=3s
          --health-retries=10

    steps:
      - name: 拉代码
        uses: actions/checkout@v4

      - name: 装 Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: pip                    # 缓存 pip 下载，第二次跑快很多

      - name: 安装依赖
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: 初始化数据库
        run: |
          sudo apt-get install -y mysql-client
          mysql -h127.0.0.1 -P3306 -uroot -p123456 < db/init.sql

      - name: 跑冒烟（提交级）
        env:
          AUTOTEST_ENV: test
          AUTOTEST_BASE_URL: http://127.0.0.1:8080
          AUTOTEST_PWD: ${{ secrets.AUTOTEST_PWD }}     # 密码从 Secrets 注入，绝不写死
        run: pytest -m smoke -v --tb=short --durations=10 --html=report.html --self-contained-html

      - name: 跑全量（仅 main 分支或夜间定时）
        if: github.ref == 'refs/heads/main' || github.event_name == 'schedule'
        env:
          AUTOTEST_ENV: test
          AUTOTEST_PWD: ${{ secrets.AUTOTEST_PWD }}
        run: pytest -v --tb=short --durations=10 --html=report-full.html --self-contained-html

      - name: 上传报告（无论成败都要传）
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-report-${{ github.run_number }}
          path: |
            report.html
            report-full.html
            artifacts/
            logs/
          retention-days: 14
```

### 2.3 六个必须理解的关键字

| 关键字 | 作用 | 常见错误 |
| --- | --- | --- |
| `on` | 触发条件 | `cron` 是 **UTC**，不是本地时间 |
| `jobs` | 任务集合，默认**并行** | 需要顺序时用 `needs: other-job` |
| `runs-on` | 跑在哪个 runner | GitHub 托管 runner 是干净容器，**没预装你的工具** |
| `steps` | 顺序执行的步骤 | 任一步失败，后续默认跳过（除 `if: always()`） |
| `if: always()` | 无论如何都执行 | **上传报告、发通知必须加**，否则失败时报告丢失 |
| `secrets` | 加密变量 | 只能在 env/with 里用，**不能在 `if:` 里直接引用** |

### 2.4 三个容易忽略的细节

**① `--tb=short` 很重要**

CI 日志里默认的完整堆栈会把报错埋在一堆无关键帧里。加 `--tb=short` 让日志直接到断言那一行，**这是"会看 CI 日志"和"不会看"的分界线**。

再加上 `-ra`（简短汇总失败原因），pytest.ini 里配一次就全生效：

```ini
[pytest]
addopts = -ra --tb=short --strict-markers
```

**② `cache: pip` 能省一半时间**

没有缓存的流水线每次都要重新下载所有依赖，30 个包可能要 2 分钟。加 `cache: pip` 后第二次开始几秒钟。

**③ 失败时报告必须上传**

`if: always()` 少写一次，就会出现"失败了，但报告没传，只能重跑一遍"的浪费。

### 2.5 手动触发带参数

```yaml
on:
  workflow_dispatch:
    inputs:
      env:
        description: "环境"
        required: true
        default: "test"
        type: choice
        options: [test, dev, staging]
```

```yaml
      - name: 用手动参数跑
        env:
          AUTOTEST_ENV: ${{ inputs.env }}
        run: pytest -m smoke -v
```

这样"发版前手动跑一次 staging"就不用改代码了。

---

## 3. 看日志定位失败（自查要求"失败时能定位到具体步骤和原因"）

### 3.1 定位流程

```
1. 看哪一步是红叉（job 里会标出失败的 step）
2. 展开这一步的日志，从下往上读（错误通常在末尾）
3. 关键词搜索：ERROR / FAILED / ModuleNotFound / Connection refused / AssertionError
4. 如果是测试失败：看 pytest 摘要（FAILED 列表 + -ra 的简短原因）
5. 如果日志不够用：去 artifact 里下载 HTML 报告和 artifacts/ 的失败现场 JSON
```

### 3.2 常见失败原因分类（对着查最快）

| 日志现象 | 原因 | 处理 |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'xxx'` | 依赖没写进 requirements.txt | 补依赖；本地能跑是因为本地装过 |
| `Connection refused` / `UnknownHostException` | 服务没起 / 地址写错 | 检查 `services` 配置、环境变量 |
| `AUTOTEST_PWD` 为空 | Secrets 没配或名字拼错 | 仓库 Settings → Secrets 检查 |
| `Permission denied` | 脚本没有执行权限 | `chmod +x`，或提交时丢失了权限位 |
| `No space left on device` | 日志/产物太多 | 清理 artifact，加保留天数 |
| 用例在本地过、CI 挂 | 环境差异（时区/编码/数据/并行） | 见下 |

**"本地过、CI 挂"的四个高频原因**（测开一定会遇到）：

| 原因 | 表现 | 解法 |
| --- | --- | --- |
| 依赖范围没锁 | 昨天过今天挂 | `requirements.txt` 锁 `==` |
| 时区不同 | 时间断言失败（UTC vs +8） | 统一用 UTC 或显式设 `TZ=Asia/Shanghai` |
| 用例依赖执行顺序 | 单独跑过、一起跑挂 | 用例必须独立，数据用 fixture 造 |
| 依赖外部环境（内网服务） | `Connection refused` | CI 里用 mock server 替代 |
| 并行冲突 | 随机失败 | 独立账号/独立数据，或串行跑该模块 |

### 3.3 重跑的正确姿势

```yaml
# 只重跑失败的 job（GitHub UI 上点 Re-run failed jobs）
# 或用 pytest 的 --lf 在本地复现
pytest --lf -v
```

**态度**：重跑一次是正常排查（确认是否 flaky）；**重跑三次就过了**，要登记 flaky 并去找原因，别把它当解决方案。

---

## 4. Jenkins 的对应概念（多数公司在用）

```groovy
// Jenkinsfile（Declarative Pipeline）
pipeline {
    agent { label 'linux && docker' }
    options {
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '50'))
    }
    triggers {
        cron('H 2 * * *')                // 每天 2 点（H = 随机分钟，避免所有任务同一时刻）
        pollSCM('H/15 * * * *')          // 每 15 分钟检查代码变化
    }
    stages {
        stage('准备') {
            steps {
                checkout scm
                sh 'python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt'
            }
        }
        stage('冒烟') {
            steps { sh '. .venv/bin/activate && pytest -m smoke -v --tb=short' }
            post {
                always { junit 'reports/junit.xml' }          // 让 Jenkins 展示用例统计
            }
        }
        stage('全量') {
            when { branch 'main' }
            steps { sh '. .venv/bin/activate && pytest -v --html=reports/report.html' }
            post {
                always { archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true }
            }
        }
    }
    post {
        failure {
            dingtalk accessToken: env.DINGTALK_TOKEN,   // 插件或 sh curl webhook
                     title: "构建失败: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                     text: "详见: ${env.BUILD_URL}"
        }
    }
}
```

**对应关系**（会 GitHub Actions 就基本会 Jenkins）：

| GitHub Actions | Jenkins |
| --- | --- |
| `on:` | `triggers {}` |
| `jobs` / `steps` | `stages` / `steps` |
| `services`（容器依赖） | 起 docker 容器或 `agent` 里装 |
| `actions/upload-artifact` | `archiveArtifacts` |
| `actions/cache` | 缓存配置或 workspace 复用 |
| `secrets` | Jenkins Credentials（`withCredentials`） |
| `if: always()` | `post { always { ... } }` |

---

## 5. 自查 Q9 完整作答

### Q9. 描述一条 GitHub Actions 流水线：什么时候触发、跑什么、产物在哪、失败了怎么通知

**按你要的四点回答：**

**① 触发**

> 三到四个触发点，各有分工：
> - `push` 到 `main`/`develop`：合并后自动回归。
> - `pull_request` 到 `main`：**这是门禁**，PR 提上来就跑，红了不许合。
> - `schedule`（cron）：每天凌晨 2 点跑全量 + UI，因为提交级只跑冒烟。注意 cron 是 **UTC**，`0 18 * * *` 才是北京时间 02:00。
> - `workflow_dispatch`：手动触发，通常带环境参数（test/staging），发版前用。
> 另外加 `concurrency` + `cancel-in-progress`，同一分支有新的提交就取消旧的，避免结果混乱和额度浪费。

**② 跑什么**

> 分三层，按耗时递增：
> - **准备**：checkout → setup-python（开 `cache: pip`）→ 装依赖 → 用 `services` 起一个干净的 MySQL 并初始化库表。**依赖环境用容器起，保证每次从零开始。**
> - **冒烟**（每次触发）：`pytest -m smoke`，要求 5 分钟内出结果，不然就阻塞开发了。
> - **全量**（`if: github.ref == 'refs/heads/main' || schedule`）：只在合并到 main 或夜间跑。
> 关键配置是 `--tb=short` 让日志直接到断言行，`--durations=10` 暴露慢用例。

**③ 产物在哪**

> 两层：
> - **artifact**（`actions/upload-artifact`）：HTML 报告、`artifacts/` 里的失败现场 JSON、`logs/`，保留 14 天。**必须加 `if: always()`**，否则失败时报告不上传，等于白跑。
> - **PR 页面的检查状态**：PR 上会显示 pass/fail，这是给 reviewer 看的第一眼信息。
> 如果接 Allure，就再起一个服务或传到对象存储，从 artefact 解压后打开。

**④ 失败怎么通知**

> 三层：
> - **平台内**：PR 上标红 + 邮件/DM 给提交者（GitHub 自带，不用配）。
> - **IM 群**：用 webhook（企业微信/钉钉/Slack），在 `post { failure { ... } }` 或单独的 job 里发，消息里带**失败用例名 + 报告链接 + 构建号**。只发"构建失败"没有价值，必须让人一眼能定位。
> - **门禁**：分支保护规则里把该 check 设为必需，失败就禁止合并 —— **这才是 CI 真正起作用的地方，不是通知，是拦截。**

**再补一句加分项：**

> 我会特别关注两件事：**流水线耗时**和 **flaky 率**。前者决定开发会不会绕过它（超过 15 分钟就有人开始要求"跳过测试"），后者决定大家还信不信它（一周三次误报之后就没人看了）。所以提交级只跑冒烟，全量放夜间，并且给 flaky 用例登记、限期修复，而不是靠 `--reruns` 掩盖。

---

## 6. 动手清单

- [ ] 在一个仓库里建 `.github/workflows/api-tests.yml`，用 §2.2 的模板跑通一次（哪怕是 3 条用例）。
- [ ] 故意让一条用例失败，看失败日志长什么样，练习用 `--tb=short` 后的定位过程。
- [ ] 加上 `if: always()` 上传报告，下载一次 artifact 看看里面有什么。
- [ ] 配一个 IM webhook，让失败时真的发一条消息到群里。
