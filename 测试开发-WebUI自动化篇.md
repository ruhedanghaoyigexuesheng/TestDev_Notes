# 测试开发-WebUI自动化篇

> 对应清单：Web UI 自动化工具选型【必须掌握一个主力】+ Playwright 核心【以它为主线】
> 对应自查：Q1（为什么 UI 自动化在金字塔顶端且最薄）、Q3（Playwright 自动等待 vs Selenium 显式等待，什么时候还得手动等）
> 立场：2026 年新学，主力选 Playwright，但 Selenium 的 **WebDriver 原理和两种等待的区别**必须能讲 —— 面试问的就是这个。

---

## 0. 先定位：UI 自动化的真实处境

| 现实 | 应对 |
| --- | --- |
| 最脆弱、最慢、维护成本最高 | 所以只放最关键的 20% 场景（冒烟 + 核心链路） |
| 元素一改就崩 | 所以 POM + test_id 策略（见《UI自动化工程化篇》） |
| 失败原因最难判断 | 所以要有失败现场五件套（截图/Trace/日志/HTML/网络） |
| 但它是唯一能验证"用户真的能用"的手段 | 所以不能没有 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 三工具选型与判断 | 能讲清 | 面试常问"为什么选它" |
| Playwright 选择器策略 | 熟练 | 决定脚本寿命 |
| 自动等待原理 | 熟练 | Q3 核心 |
| 网络拦截 Mock | 会用 | 测前端异常处理必用 |
| Trace 调试 | 熟练 | 定位神器 |
| WebDriver 原理 + 显隐等待 | 能讲清 | 面试必备（Selenium 存量） |

---

## 1. 工具选型：为什么新学选 Playwright

### 1.1 三款对比

| | Playwright | Selenium | Cypress |
| --- | --- | --- | --- |
| 出品 | 微软（2020） | 开源社区（2004） | Cypress.io |
| 通信方式 | CDP / 浏览器专用协议直连 | **W3C WebDriver 协议**（HTTP 请求驱动浏览器） | 跑在浏览器内部 |
| 等待机制 | **内置自动等待**（actionability 检查） | 需自己写显式等待 | 自动重试（命令级） |
| 多浏览器 | Chromium/Firefox/WebKit **一套代码** | 需要各 driver | 主要 Chromium/Firefox，WebKit 弱 |
| 多标签/多窗口 | 原生支持 | 支持但麻烦 | **不支持多标签**（架构限制） |
| iframe/新窗口 | 简单 | 需 switch_to | 有限制 |
| 调试 | **Trace Viewer**（时间轴回放，含网络/快照） | 靠日志和截图 | 时间旅行调试 |
| 并行 | 内置 worker | 需 Grid | 有但收费项多 |
| 移动端 | 只能模拟视口 | 有 Appium 生态 | 无 |
| 生态/存量 | 新，增长快 | **巨大**，企业存量最多 | 前端团队多 |

**2026 年新学的判断**：

```
新项目主线 → Playwright（等待机制、Trace、多引擎、并行都省心）
面试与存量 → Selenium（WebDriver 原理、显隐等待、Grid，问得最多）
前端团队已用 → Cypress（跟着团队走，别硬换）
```

**一个具体的差距例子**：点一个按钮。

```python
# Selenium：你要自己判断"什么时候能点"
wait = WebDriverWait(driver, 10)
wait.until(EC.element_to_be_clickable((By.ID, "submit"))).click()

# Playwright：click 内置了"等到可点击"的检查
page.get_by_role("button", name="提交").click()
```

后者看起来只是短，实质是**它把"元素可见、稳定（不在动画中）、可用、能接收事件"这四项检查做进了每个操作**。这就是自动等待。

### 1.2 什么时候不该选 Playwright

| 场景 | 原因 |
| --- | --- |
| 团队已有成熟 Selenium 框架 + Grid 基础设施 | 迁移成本 > 收益 |
| 需要驱动**真实 App** | Playwright 只能模拟移动视口，不能测原生 App（用 Appium） |
| 需要兼容很老的浏览器（IE） | Playwright 不支持 |
| 需要分布式大规模并发（几十台机器） | Selenium Grid 生态更成熟 |

---

## 2. Playwright 核心

### 2.1 跑起来

```bash
pip install playwright pytest-playwright
playwright install              # 装浏览器（chromium/firefox/webkit）
```

```ini
# pytest.ini
[pytest]
addopts = --browser chromium --headed --tracing retain-on-failure --output test-results
```

```python
# tests/test_login.py
from playwright.sync_api import Page, expect


def test_login_success(page: Page):
    page.goto("https://app.test.example.com/login")
    page.get_by_label("用户名").fill("qa01")
    page.get_by_label("密码").fill("P@ss1234")
    page.get_by_role("button", name="登录").click()
    expect(page.get_by_text("欢迎回来")).to_be_visible()
```

`pytest-playwright` 提供的 fixture：`page` / `context` / `browser` / `playwright` / `browser_name`。

### 2.2 选择器策略：这一条决定脚本能活多久

**优先级（从高到低）**：

| 优先 | 写法 | 为什么 |
| --- | --- | --- |
| 1 | `get_by_test_id("submit-order")` | 专门给测试的锚点，不随样式和文案变 |
| 2 | `get_by_role("button", name="提交订单")` | 语义化，接近用户和可访问性标准；文案变才会失效 |
| 3 | `get_by_label("手机号")` / `get_by_placeholder("请输入手机号")` | 表单场景好用 |
| 4 | `get_by_text("订单已创建")` | 断言场景好用，做定位偏脆 |
| 5 | CSS：`#order-form .btn-primary` | 样式一改就崩 |
| 6 | XPath：`//div[3]/form/button[2]` | **绝对不要**，层级一改全废 |

**推动团队加 `data-testid`** 是最值得做的一次性投入：

```tsx
// 前端
<button data-testid="submit-order">提交订单</button>
```

```python
# 测试
page.get_by_test_id("submit-order").click()
```

对比一下三种写法的存活率：

```
get_by_test_id("submit-order")      → 只有产品逻辑变了才需要改
get_by_role("button", name="提交订单") → 按钮文案改了就要改
#order-form > div:nth-child(3) > button → 后端加一个 div 就崩
```

**面试可以这样说**：选择器策略本质是在"定位的稳定性"和"实现成本"之间做取舍，我优先用 `data-testid`，因为它和样式、文案、DOM 结构都解耦，是唯一能让 UI 自动化"改版不崩"的手段。

### 2.3 自动等待：为什么比 sleep 可靠

Playwright 在执行 `click()` / `fill()` 前，会对目标元素做**actionability 检查**，全部通过才执行：

| 检查 | 含义 |
| --- | --- |
| Visible（可见） | 不是 `display:none`、`visibility:hidden`、尺寸为 0 |
| Stable（稳定） | 连续两帧位置没变（不在动画中） |
| Enabled（可用） | 不是 disabled |
| Receives Events（能接收事件） | 没有被其他元素遮挡 |

**和 `sleep(3)` 的本质区别**：

| | `sleep(3)` | 自动等待 |
| --- | --- | --- |
| 等待依据 | 猜一个时间 | 元素的真实状态 |
| 快的情况 | 白等 2.8 秒 | 元素一就绪就继续 |
| 慢的情况 | 3 秒不够就失败（flaky） | 一直等到超时（默认 30s） |
| 慢机器 | 必然失败 | 不受影响 |

**这就是"死等"和"条件等"的差别**：`sleep` 是**赌**，自动等待是**问**。

### 2.4 网络拦截与 Mock：测前端的异常处理

```python
import json


def test_pay_error_shows_friendly_message(page: Page):
    """后端 500 时，前端要有友好提示，而不是白屏或报错堆栈。"""
    # 拦截支付接口，返回 500
    page.route("**/api/pay", lambda route: route.fulfill(
        status=500,
        content_type="application/json",
        body=json.dumps({"code": 500, "msg": "系统繁忙"}),
    ))

    page.goto("https://app.test.example.com/checkout")
    page.get_by_role("button", name="支付").click()

    expect(page.get_by_text("系统繁忙，请稍后重试")).to_be_visible()
    expect(page.get_by_text("500")).to_have_count(0)      # 不能把技术细节暴露给用户


def test_slow_api_loading_state(page: Page):
    """接口慢时要有 loading，且按钮不能重复点。"""
    def slow(route):
        import time
        time.sleep(3)
        route.fulfill(status=200, body='{"code":0}')

    page.route("**/api/order", slow)
    page.get_by_role("button", name="提交").click()
    expect(page.get_by_test_id("loading")).to_be_visible()
    expect(page.get_by_role("button", name="提交")).to_be_disabled()
```

**这一节的价值**：这些场景（后端 500、超时、慢响应、返回畸形数据）**只有 mock 能造**，真实环境里你等不到。而前端的容错恰恰是 bug 高发区。

### 2.5 调试三件套：Trace / 截图 / 录屏

| 工具 | 什么时候看 | 能看到什么 |
| --- | --- | --- |
| **Trace Viewer** | 失败复盘首选 | **时间轴回放**：每一步的 DOM 快照、网络请求、console、截图 |
| 截图 | 快速看界面 | 失败时的样子 |
| 录屏（video） | 看过程（比如"闪一下"的问题） | 整个用例的执行过程 |

```python
# pytest 插件方式（推荐）：只保留失败的 trace
# pytest.ini: addopts = --tracing retain-on-failure --video retain-on-failure

# 手动方式：精细控制
context = browser.new_context()
context.tracing.start(screenshots=True, snapshots=True, sources=True)
# ... 操作 ...
context.tracing.stop(path="trace.zip")
```

```bash
playwright show-trace trace.zip     # 打开 Trace Viewer
```

**Trace 为什么强**：它不只是录屏，**每一步都有当时的 DOM 快照**，你可以点开"点击按钮前"的那个快照，用 DevTools 检查元素，看到底是元素不存在、被遮挡、还是状态不对。这是查 flaky 最快的工具。

### 2.6 多浏览器与移动视口

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    for engine in (p.chromium, p.firefox, p.webkit):
        browser = engine.launch()
        page = browser.new_page()
        page.goto("https://app.test.example.com")
        browser.close()
```

```python
# 移动视口（注意：这是"模拟"，不是真机）
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    iphone = p.devices["iPhone 13"]                 # 内置设备参数（UA、视口、DPR、触摸）
    browser = p.chromium.launch()
    context = browser.new_context(**iphone)
    page = context.new_page()
```

**要清楚边界**：`p.devices[...]` 只是改 UA、视口尺寸、触摸事件，**它跑的还是 PC 浏览器内核**。真实设备的渲染差异、性能差异、系统弹窗、摄像头权限，它都测不了 → 那部分要用 Appium + 真机（见《App自动化篇》）。

---

## 3. Selenium：面试要能讲的两件事

### 3.1 WebDriver 原理（W3C 协议）

```
测试代码 → 通过 HTTP 发 W3C 命令 → driver（chromedriver/geckodriver） → 浏览器
```

| 要点 | 说明 |
| --- | --- |
| 客户端-服务端模型 | 测试代码是 client，driver 是 server（监听端口，如 chromedriver 9515） |
| 通信协议 | **W3C WebDriver 标准**，HTTP + JSON |
| 为什么需要 driver | 浏览器只接受调试协议（CDP），driver 是翻译层 |
| 结论 | 所以 Selenium 天然能跨语言（Java/Python/JS 都行），因为它只是发 HTTP |

**面试追问的答案**：`driver.get()` 本质是发一个 `POST /session/{id}/url` 请求，driver 收到后通过 CDP 等内部协议驱动浏览器。

### 3.2 显式等待 vs 隐式等待 vs 硬等待

| 类型 | 写法 | 机制 | 问题 |
| --- | --- | --- | --- |
| **硬等待** | `time.sleep(3)` | 死等 | 快则白等，慢则失败 |
| **隐式等待** | `driver.implicitly_wait(10)` | 全局生效：**查找元素**时最多等 10s | 只管"元素存在"，不管"可点击"；对所有 `find_element` 都生效，容易掩盖问题 |
| **显式等待** | `WebDriverWait(driver,10).until(EC.xxx)` | 等**某个条件**成立 | 要自己写条件，但最精确 |

**关键区别（面试高频）**：

```
隐式等待  → 等"元素出现"，全局生效，只能等存在性
显式等待  → 等"任意条件"，针对具体元素和条件，最灵活
```

**两者混用会出事**：隐式等待 + 显式等待叠加，实际等待时间可能是乘积（`implicitly_wait(10)` + `WebDriverWait(10)` 最坏情况等到 100s），所以要**选一个用，Selenium 官方推荐只用显式等待**。

---

## 4. 自查 Q1 完整作答：为什么 UI 自动化在金字塔顶端且最薄

### 4.1 用投入产出比回答（这是题眼）

| 维度 | 单元测试 | 接口测试 | UI 测试 |
| --- | --- | --- | --- |
| 单条用例耗时 | 毫秒 | 几十~几百毫秒 | **秒到几十秒** |
| 1000 条用例总时长 | 几十秒 | 几分钟 | **1~3 小时** |
| 环境依赖 | 无 | 服务 + 数据库 | 服务 + 数据库 + **浏览器 + 前端静态资源 + CDN** |
| 失败原因种类 | 几乎只有代码逻辑 | 请求/数据/业务 | **+ 渲染、网络、动画、元素变化、浏览器版本、分辨率** |
| 单个缺陷定位成本 | 看断言就够 | 看请求响应 | **要看 Trace/截图/日志才能判断是谁的问题** |
| 维护成本 | 重构时跟着改，逻辑清晰 | 接口改了才改 | **页面改版就要大面积改选择器** |
| 能覆盖的问题 | 逻辑分支 | 契约、业务、并发 | **到"用户真的能用"这一层（这是唯一的不可替代价值）** |

**结论的逻辑链**：

```
同样一条缺陷，UI 层发现的修复成本比接口层高一个数量级（越晚发现越贵）
↑
但全用 UI 覆盖，用例数量会是接口层的 N 倍，执行时间变小时级，维护成本指数上升
↑
所以：把"能下沉的验证"全部下沉到接口层（业务逻辑、状态、边界、并发）
     把"必须端到端"的留在 UI 层（关键链路能不能走通、关键交互是否正常、前端容错）
↑
结果：UI 层少而精，只放冒烟 + 核心链路
```

### 4.2 60 秒口头版

> UI 自动化放顶端且最薄，是投入产出比决定的。
> **产出侧**：它能证明"用户真的能用"，这是接口测试证明不了的（前端渲染、交互、容错、跨浏览器）。
> **投入侧**：单条用例秒级、依赖浏览器和前端资源、失败原因最复杂、页面一改就要维护选择器 —— 它是最贵的一层。
> 所以策略是**把能下沉的验证都下沉到接口层**（业务规则、状态机、边界、并发、幂等），接口层又快又能定位；UI 层只保留"必须端到端才能验证"的部分：核心业务链路能不能走通、关键交互（上传/弹窗/支付跳转）、前端容错（后端 500 时的提示）。
> 判断标准很简单：**这条用例能不能用接口测？能，就不要用 UI 测。**

### 4.3 一个数字对比（讲这个故事更有说服力）

> 我们下单流程有 40 个业务场景（优惠券、库存、限流、幂等…）。
> 放在接口层跑：40 条用例，约 2 分钟。
> 放在 UI 层跑：40 条用例，约 25 分钟，且每季度因页面改版要修 5~8 条选择器。
> 所以 UI 层只保留了 3 条：正常下单、支付跳转、下单失败提示。其余 37 条全部下沉到接口层。

---

## 5. 自查 Q3 完整作答：自动等待 vs 显式等待，什么时候还得手动等

### 5.1 两者的区别（核心在"等什么"）

| | Playwright 自动等待 | Selenium 显式等待 |
| --- | --- | --- |
| 等什么 | **元素的可操作性**（可见、稳定、可用、能接收事件） | **你写的任意条件**（存在、可见、可点击、文本变化…） |
| 触发时机 | 每次 `click/fill/...` 自动触发 | 你显式调用 `WebDriverWait(...).until(...)` |
| 粒度 | 内建四项检查，不可扩展 | 完全自定义（`EC.presence_of_element_located` 等） |
| 定位不到元素时 | 自动重试到超时 | 立即抛 `NoSuchElementException`（除非用显式等待包住） |
| 失败信息 | 告诉你卡在哪个 actionability 检查 | 告诉你超时 + 条件表达式 |

**一句话**：**Playwright 把"最常见的等待"内建了；Selenium 把等待交给你自己写。**

### 5.2 什么场景**仍然需要**手动等待（这是 Q3 的重点）

自动等待只管"元素状态"，**管不了"业务状态"和"异步链路"**。五类：

| 场景 | 为什么自动等待不够 | 怎么写 |
| --- | --- | --- |
| **等业务状态变化** | 元素一直"可见"，但内容/状态在变（"处理中"→"已成功"） | `expect(page.get_by_test_id("status")).to_have_text("已成功")`（Playwright 的 expect 会自动重试） |
| **等接口响应** | 页面元素没变，但数据在请求中 | `page.wait_for_response("**/api/order")` 或 `page.expect_response(...)` |
| **等元素消失/被移除** | 自动等待只等"出现"，不等"消失" | `page.get_by_text("加载中").wait_for(state="detached")` |
| **等文件下载/上传完成** | 不是 DOM 状态 | `page.expect_download()` / `set_input_files` + 等提示 |
| **等异步任务（轮询接口）** | 后端异步处理，前端轮询 | 写 `expect.poll`（JS/TS）或自己轮询 SQL/接口，Python 里用 `page.wait_for_function` 或直接断言接口 |
| **等动画结束** | 自动等待的 stable 检查只保证"两帧没动"，长动画可能误判 | 关掉动画（`page.add_style_tag` 禁 transitions）或 `wait_for_timeout`（最后手段） |

**代码示例：等业务状态**

```python
from playwright.sync_api import Page, expect


def test_refund_status_changes_to_success(page: Page):
    """自动等待保证按钮可点，但"退款中→已退款"是业务状态，要自己等。"""
    page.get_by_role("button", name="申请退款").click()

    # ❌ 错：按钮一下就可见，点完马上断言会拿到"退款中"
    # assert page.get_by_test_id("refund-status").inner_text() == "已退款"

    # ✅ 对：expect 会轮询直到超时（默认 5s），天然带重试
    expect(page.get_by_test_id("refund-status")).to_have_text("已退款", timeout=30000)
```

**代码示例：等接口响应**

```python
def test_order_created_by_api(page: Page):
    with page.expect_response("**/api/orders") as resp_info:
        page.get_by_role("button", name="提交订单").click()
    resp = resp_info.value
    assert resp.status == 201
    order_no = resp.json()["data"]["order_no"]
    expect(page.get_by_text(order_no)).to_be_visible()
```

### 5.3 什么时候可以用 `sleep`（最后的例外）

只有两种情况：

1. **等外部系统**（比如第三方回调、邮件到达），这时候连"可观测的状态"都没有，只能用轮询 + 超时。
2. **排查问题时的临时手段**，验证完必须删掉。

**纪律**：`sleep` 出现在代码里必须有注释说明原因，否则 review 直接打回。**统计一下代码里 `sleep` 的条数，就知道框架成熟度。**

---

## 6. 动手清单

- [ ] 推动前端给 3 个核心页面加 `data-testid`，把对应用例的选择器换掉，体会稳定性的差异。
- [ ] 用 `route` mock 一次后端 500，验证前端提示是否友好（这通常能测出 bug）。
- [ ] 跑一次带 `--tracing retain-on-failure` 的用例，用 `playwright show-trace` 打开失败 trace。
- [ ] 数一下现有脚本里 `sleep` 的数量，逐个换成条件等待。
