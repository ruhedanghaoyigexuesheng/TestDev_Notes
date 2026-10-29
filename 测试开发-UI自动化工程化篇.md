# 测试开发-UI自动化工程化篇

> 对应清单：工程化要点【必须掌握】+ AI 在 UI 自动化中的用法【了解即可】
> 对应自查：Q2（POM 分层与改版时改哪里）、Q4（脚本问题 vs 业务坏了）、Q5（用例依赖别的用例的登录账号怎么解耦）、Q6（flaky 治理与重试策略）、Q8（AI 生成脚本后必须人工检查什么）
> 立场：**UI 自动化的稳定性来自工程设计，不是来自工具**。同样是 Playwright，两个人写出来的脚本寿命能差三倍，差别全在这一篇。

---

## 0. 先定位：工程化解决的是"三个月后还能不能跑"

| 不做工程化 | 做了 |
| --- | --- |
| 页面改版，50 个文件全要改 | 只改 Page 层一个文件 |
| 用例 A 挂了导致 B、C 全挂 | 每条独立，互不影响 |
| 失败只知道"点不动" | 有截图/Trace/网络，判断是脚本还是业务 |
| 每周修 flaky，修不完 | flaky 率 < 1%，有人盯 |
| 全量 3 小时，跑不完 | 分三级，提交级 15 分钟 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| POM 三层分层 | 熟练 | 决定维护成本 |
| 失败现场五件套 | 熟练 | 决定定位效率 |
| 登录态复用 / 数据隔离 | 熟练 | 决定能否并行 |
| flaky 治理 | 会用能讲 | 面试加分项 |
| 用例分级 | 熟练 | 决定 CI 能不能用 |

---

## 1. 自查 Q2：POM 分层怎么设计，改版时只改哪里

### 1.1 分三层（不要只分两层）

```
BusinessFlow（业务流）  ← "下单"这个动作，由多个页面步骤组成
      ↓
   Page（页面）        ← 一个页面的元素 + 原子操作（填、点、断言）
      ↓
Component（组件）      ← 可复用的部件（顶部导航、弹窗、日期选择器）
      ↓
  Locator（定位器）    ← 所有选择器集中定义
```

| 层 | 职责 | 改版时会不会改 |
| --- | --- | --- |
| **Locator** | 只放选择器 | **改（样式/结构变了）** |
| **Page** | 一个页面的元素引用 + 原子操作 + 页面级断言 | 改（元素增删） |
| **Component** | 跨页面复用的部件（弹窗、头部、分页器） | 改（如果这个部件变了） |
| **BusinessFlow** | 业务步骤编排（下单 = 加购 + 结算 + 支付） | **几乎不改**（业务流程稳定） |

**关键洞察**：**页面改版改的是"元素"，不是"业务"**。所以元素相关的东西全部收敛到 Page 层，业务步骤（Flow 层）尽量稳定。

### 1.2 目录结构

```
tests_ui/
├── locators/
│   ├── login_locators.py        # 登录页所有选择器
│   ├── order_locators.py
│   └── common_locators.py       # 全局（弹窗关闭、toast）
├── pages/
│   ├── base_page.py             # 基类：等待、点击重试、截图等通用能力
│   ├── login_page.py            # 登录页：原子操作
│   └── order_page.py
├── components/
│   ├── header.py                # 顶部导航（跨页面复用）
│   └── modal.py                 # 弹窗组件
├── flows/
│   ├── login_flow.py            # 登录业务流程（可能涉及多个页面）
│   └── order_flow.py            # 下单流程
└── testcases/
    ├── test_login.py            # 只调用 flow，不碰选择器
    └── test_order.py
```

### 1.3 代码对比（这是最能说明问题的部分）

**❌ 反例：全写一个文件（三个月后没人敢改）**

```python
def test_buy():
    page.goto("https://app.test.com/login")
    page.fill("#username", "qa01")
    page.fill("#password", "P@ss1234")
    page.click("button.btn-primary")
    page.wait_for_timeout(2000)
    page.click("div.product-list > div:nth-child(2) > button")
    page.click("#cart-icon")
    page.click("//button[text()='结算']")
    page.click("#submit-order")
    assert page.is_visible(".success-toast")
```

**✅ 正例：三层分开**

```python
# locators/order_locators.py
class OrderLocators:
    PRODUCT_CARD = '[data-testid="product-card"]'
    ADD_TO_CART = '[data-testid="add-to-cart"]'
    CART_ICON = '[data-testid="cart-icon"]'
    CHECKOUT = '[data-testid="checkout-btn"]'
    SUBMIT_ORDER = '[data-testid="submit-order"]'
    SUCCESS_TOAST = '[data-testid="success-toast"]'
```

```python
# pages/order_page.py
from playwright.sync_api import Page, expect
from locators.order_locators import OrderLocators


class OrderPage:
    """订单相关页面的原子操作。不写业务判断，只写"怎么操作这个页面"。"""

    def __init__(self, page: Page):
        self.page = page
        self.loc = OrderLocators()

    def add_first_product_to_cart(self):
        self.page.get_by_test_id("add-to-cart").first.click()

    def go_to_checkout(self):
        self.page.get_by_test_id("cart-icon").click()
        self.page.get_by_test_id("checkout-btn").click()

    def submit_order(self):
        self.page.get_by_test_id("submit-order").click()

    def expect_success(self):
        expect(self.page.get_by_test_id("success-toast")).to_be_visible()
```

```python
# flows/order_flow.py
class OrderFlow:
    """业务流程。这里说的是"用户要做什么"，不关心元素长什么样。"""

    def __init__(self, page: Page):
        self.order_page = OrderPage(page)

    def buy_first_product(self):
        self.order_page.add_first_product_to_cart()
        self.order_page.go_to_checkout()
        self.order_page.submit_order()
        self.order_page.expect_success()
```

```python
# testcases/test_order.py
def test_buy_first_product(auth_page):
    OrderFlow(auth_page).buy_first_product()
```

### 1.4 改版时改哪里（直接回答 Q2）

| 改版类型 | 改哪里 | 改几个文件 |
| --- | --- | --- |
| 按钮换成图标（选择器变了） | **只改 `locators/`** | 1 个 |
| 页面加了新元素、要新操作 | `pages/` 加方法 | 1 个 |
| 业务流程变了（结算分两步） | `flows/` | 1 个 |
| 顶部导航改版（跨 5 个页面） | `components/header.py` | 1 个 |
| 整个结算页重做 | `pages/` + `locators/` | 2 个 |

**"改版要改 50 个文件"的根因**：定位和业务步骤混在一个文件里。**只要选择器全在 Page/Locator 层，改版就只改一处。**

### 1.5 POM 的三个反模式

| 反模式 | 问题 |
| --- | --- |
| Page 里写断言业务逻辑 | 页面对象变成"测试类"，无法复用 |
| Page 里写死等待 | 换页面就得改等待 |
| 一个 Page 类 800 行（把整个 App 写一个类） | 等于没分 |

---

## 2. 稳定等待的工程化

前面（《WebUI自动化篇》Q3）讲了"什么时候要手动等"。这里讲**怎么把等待做成框架能力**。

```python
# pages/base_page.py
from playwright.sync_api import Page, expect


class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def click_when_ready(self, locator, timeout: int = 15000):
        """封装点击：自动等可见+可用，失败时带上当前 URL 和页面标题（便于判断）。"""
        try:
            locator.click(timeout=timeout)
        except Exception as e:
            raise AssertionError(
                f"点击失败: url={self.page.url} title={self.page.title()!r} err={e}"
            ) from e

    def wait_text(self, locator, text: str, timeout: int = 15000):
        """等文本出现 —— 比"等元素可见"更贴近业务。"""
        expect(locator).to_have_text(text, timeout=timeout)

    def wait_gone(self, locator, timeout: int = 15000):
        """等元素消失（loading、遮罩）。"""
        locator.wait_for(state="detached", timeout=timeout)
```

**工程化的三条纪律**：

1. **业务层禁止 `wait_for_timeout`**（固定等待），只在排查时临时用。
2. **等待要有超时**，且超时值集中配置（不要每个地方写 3000/5000/10000 各种值）。
3. **等待失败的报错要带现场**（URL、标题、当前可见文本），而不是光一个 `TimeoutError`。

---

## 3. 自查 Q4：失败时怎么判断"脚本问题"还是"业务坏了"

### 3.1 失败现场五件套（清单给的五样）

| # | 现场 | 回答什么问题 |
| --- | --- | --- |
| 1 | **截图** | 当时页面长什么样（白屏？报错弹窗？loading？） |
| 2 | **HTML 快照（page.content）** | 元素到底在不在 DOM 里、属性是什么 |
| 3 | **网络请求**（路由日志 / Trace 里的 Network） | 接口发出去了吗、返回什么状态码、返回什么数据 |
| 4 | **Console 日志** | 前端有没有 JS 报错 |
| 5 | **Trace** | 把上面四个按时间轴串起来看（含每一步的 DOM 快照） |

**自动收集（一次配好，永久受益）**：

```python
# conftest.py
import pytest
from pathlib import Path

ARTIFACT_DIR = Path("artifacts")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    page = item.funcargs.get("page") or item.funcargs.get("auth_page")
    if page is None:
        return

    out = ARTIFACT_DIR / item.nodeid.replace("::", "_").replace("/", "_")
    out.mkdir(parents=True, exist_ok=True)

    page.screenshot(path=str(out / "screenshot.png"), full_page=True)       # ① 截图
    (out / "page.html").write_text(page.content(), encoding="utf-8")        # ② HTML 快照
    (out / "console.log").write_text(                                       # ④ console
        "\n".join(f"{m.type}: {m.text}" for m in page.console_messages), encoding="utf-8")
    report.sections.append(("失败现场", str(out)))
```

网络请求和 Trace 用 pytest-playwright 的 `--tracing retain-on-failure` 自动得到（Trace 里含完整的 Network 面板）。

### 3.2 判断流程（六步，按成本从低到高）

```
① 看截图
   白屏/报错弹窗 → 大概率业务或前端问题
   元素明显不在 → 进②

② 看 HTML 快照，搜关键元素
   元素在，但属性/文本不对  → 前端渲染或数据问题（业务）
   元素根本不在            → 脚本选择器错，或页面/接口没加载完（脚本）

③ 看网络请求
   请求没发出        → 脚本问题（按钮没点到）或前端逻辑（校验没通过）
   404/500          → 后端问题（业务）
   200 但数据不对    → 后端业务逻辑（业务）
   200 数据对但页面没渲染 → 前端问题（业务）

④ 看 console
   有 JS 报错（如 undefined） → 前端 bug（业务）
   有 404 资源                → 环境或发版问题

⑤ 手工复现同一路径
   手工也不行 → 确认是业务 bug，提单
   手工可以   → 几乎确定是脚本问题

⑥ 单独跑这条用例 / 换浏览器跑
   单独跑过、一起跑挂 → 数据污染或并发干扰（脚本/环境）
   换浏览器也挂       → 前端兼容或业务
```

### 3.3 一套判定表（值班时直接查）

| 现象 | 判断 | 依据 |
| --- | --- | --- |
| 元素找不到，HTML 里也没有 | 脚本（选择器错/页面没到） | 换 `data-testid` 或加等待 |
| 元素在但点不动（被遮挡） | 前端/业务（有过场动画、遮罩没关） | 看截图有没有遮罩 |
| 点击后接口 500 | 业务（后端） | 抓返回体 |
| 点击后接口 200，页面不更新 | 前端 bug | 看 console |
| 断言文案不对，但功能正常 | 业务（文案改了）或断言太脆 | 优先改断言方式 |
| 只有 CI 挂、本地过 | 环境（时区/分辨率/版本/网络） | 看 CI 的截图和 URL |
| 偶发，重跑就过 | flaky（等待或数据） | 见 §5 |
| 所有用例第一个都挂 | 环境（服务没起/登录失效） | 先看登录接口 |

### 3.4 答题话术

> 我不会先改脚本，先看现场。五件套里我先看**截图 + HTML 快照**：元素到底在不在 DOM 里。**在但不可点**就怀疑前端（遮罩、动画、样式）；**不在**就怀疑脚本（选择器错或没等加载完）。
> 然后看**网络请求**：接口有没有发出、返回什么。接口 500 或返回数据不对，直接是业务问题；接口正常但页面没更新，是前端问题。
> 最后一步是**手工复现**：手工也复现不了，基本就能确定是脚本问题。
> 这个顺序的理由是：截图和快照成本最低、信息量最大，比读代码快。

---

## 4. 自查 Q5：用例 A 依赖用例 B 的登录账号，怎么解耦

### 4.1 先明确"为什么必须解耦"

```
test_login  → 登录成功，把 token 存到全局变量
test_buy    → 依赖 test_login 留下的 token
test_pay    → 依赖 test_buy 留下的订单

结果：单独跑 test_pay 失败；顺序一变全挂；并行跑必挂
```

**这是 UI 自动化最常见的架构错误**：用例之间串成一个长链，任何一环断了后面全废，而且不能并行。

### 4.2 四种解耦方案（按推荐度）

| 方案 | 做法 | 适用 |
| --- | --- | --- |
| **① 复用登录态（storage_state）** | 一次登录，把 cookie+localStorage 存成文件，每条用例新建 context 时加载 | **Playwright 项目首选** |
| **② 每条用例独立登录** | 每条自己走登录流程 | 简单但慢（每条多 3~5 秒） |
| **③ API 造账号 + API 登录** | 用接口注册/登录，把 token/cookie 注入浏览器 | 最快，最推荐组合方案 |
| **④ 每条用例独立账号** | 账号池，按 worker 分配 | 需要账号隔离时的补充 |

### 4.3 方案 ①：storage_state（最干净的解法）

```python
# conftest.py
import pytest
from playwright.sync_api import Browser


@pytest.fixture(scope="session")
def auth_state(browser: Browser, base_url: str) -> str:
    """全局只登录一次，把登录态存文件。后面所有用例复用。"""
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{base_url}/login")
    page.get_by_label("用户名").fill("qa01")
    page.get_by_label("密码").fill("P@ss1234")
    page.get_by_role("button", name="登录").click()
    page.get_by_text("欢迎回来").wait_for()

    path = ".auth/state.json"
    context.storage_state(path=path)      # 保存 cookie + localStorage
    context.close()
    return path


@pytest.fixture
def auth_page(browser: Browser, auth_state: str):
    """每条用例一个干净的 context，但带着登录态。用例之间互不影响。"""
    context = browser.new_context(storage_state=auth_state)
    page = context.new_page()
    yield page
    context.close()


# 用例里直接用 auth_page，不需要先跑登录用例
def test_buy(auth_page):
    OrderFlow(auth_page).buy_first_product()
```

**这个方案同时解决了三件事**：

1. 用例之间不依赖（每条独立 context）。
2. 可以并行（context 隔离，session 级只有一次登录）。
3. 跑得快（不用每条都登录）。

### 4.4 方案 ③：API 造号（数据也一起解决）

```python
@pytest.fixture
def fresh_user(api):
    """每条用例一个全新账号（API 造），彻底隔离。"""
    phone = f"139{uuid.uuid4().hex[:8]}"
    api.post("/api/register", json={"phone": phone, "pwd": "P@ss1234"})
    return {"phone": phone, "pwd": "P@ss1234"}


def test_order_with_new_user(browser, base_url, fresh_user):
    context = browser.new_context()
    page = context.new_page()
    # 用新账号登录（或用 API 换 cookie 注入）
    ...
```

### 4.5 反模式（对照检查）

| 反模式 | 后果 |
| --- | --- |
| 用全局变量传 token | 并行时互相覆盖 |
| 用例按文件名顺序执行（`test_01_login`、`test_02_buy`） | 单独跑必挂，顺序一变全挂 |
| `--lf` 只跑失败用例 | 因为依赖前置用例，单独跑根本跑不起来 |
| session fixture 里登录 + 全局 page 复用 | 用例之间状态污染（上个用例停在别的页面） |

---

## 5. 自查 Q6：flaky 用例治理与重试策略

### 5.1 什么是 flaky，为什么危险

> 同一份代码，不做任何改动，重复执行时好时坏。

**危险性不在于它挂，而在于它会消耗信任**：

```
第 1 次：挂了 → 查看 → 发现是 flaky
第 2 次：挂了 → 查看 → 又是 flaky
第 3 次：挂了 → 不看了，直接重跑
第 10 次：挂了 → 真 bug 也被当成 flaky
```

**所以 flaky 率是个质量指标，不是"修不修都行"的东西。** 行业经验：超过 1~2%，团队就会开始无视失败。

### 5.2 归因（这一步决定能不能修）

| 类别 | 占比（经验） | 表现 | 修法 |
| --- | --- | --- | --- |
| **等待不足** | 最大 | 偶发"元素找不到/点不到" | 换条件等待，禁 sleep |
| **数据污染** | 大 | 偶发"数据已存在/已被使用" | 数据隔离 + 前置清理 |
| **选择器不稳** | 中 | 匹配到多个元素、匹配到隐藏元素 | 加 testid、加 `.first` 前先确认唯一 |
| **环境抖动** | 中 | 第三方慢、服务冷启动、CI 机器慢 | 环境检查 + 合理的超时 |
| **真 bug（间歇）** | 少但重要 | 并发问题、时序问题 | **这才是要提的缺陷** |

**怎么归因**：给 flaky 用例打 tag，连续记录 5 次失败时的现场（截图 + Trace），看是否同一原因。**不同原因的"偶发"要分开修**。

### 5.3 治理流程（四步）

```
① 登记：所有 flaky 用例进清单（用例名 + 首次发现时间 + 失败率 + Owner）
② 分类：按 §5.2 归因
③ 修复：数据 > 等待 > 选择器（按影响面排序，能自动化的先自动化）
④ 监控：每周统计 flaky 率，超阈值（如 1%）的模块要专项治理
```

### 5.4 重试策略：怎么开才不掩盖问题

**允许重试的三类**：

```
1. 第三方依赖的已知不稳定（支付回调、短信、第三方登录）
2. 环境抖动，有监控证实的（CI 机器负载高、服务冷启动）
3. 已登记 flaky 且已定位到原因、正在修（带期限）
```

**绝不允许**：

```
× 全局 --reruns 3（让所有失败都重试）
× 没有登记就重试
× 重试成功就算通过，不留记录
```

### 5.5 留痕式重试（关键实现）

```ini
# pytest.ini —— 不全局开，靠标记
[pytest]
addopts = -ra --strict-markers
markers =
    flaky: 已知不稳定，允许重试（必须有 JIRA 号）
```

```python
import pytest

@pytest.mark.flaky(reruns=2, reason="JIRA-1234 第三方支付沙箱不稳定")
def test_pay_with_third_party(auth_page):
    ...
```

**重试要能统计出来**（这是"不掩盖问题"的关键实现）：

```python
# conftest.py —— 记录哪些用例是靠重试才过的
RETRIED = []


def pytest_runtest_logreport(report):
    # pytest-rerunfailures 会在 outcome 里标记 rerun
    if report.outcome == "rerun":
        RETRIED.append(report.nodeid)
    if report.outcome == "passed" and report.nodeid in RETRIED:
        RETRIED.append(f"PASSED_ON_RETRY:{report.nodeid}")


def pytest_sessionfinish(session, exitstatus):
    on_retry = [r for r in RETRIED if str(r).startswith("PASSED_ON_RETRY:")]
    if on_retry:
        print(f"\n⚠️ 以下 {len(on_retry)} 条用例是靠重试才通过的（需登记治理）：")
        for r in on_retry:
            print("  -", str(r).split(":", 1)[1])
```

```bash
# 或者直接用 pytest-rerunfailures 的报告能力
pytest --reruns 2 --reruns-delay 3 -ra
# 报告里会显示 RERUN 状态
```

### 5.6 三个指标（用来证明治理有效）

| 指标 | 算法 | 目标 |
| --- | --- | --- |
| flaky 率 | 重试后才通过的用例数 / 总用例数 | < 1% |
| 平均修复时长 | flaky 从登记到关闭的天数 | < 7 天 |
| 重试占比 | 有 reruns 标记的用例 / 总用例 | < 5% |

### 5.7 答题话术

> flaky 我是当缺陷管的，不是当"重跑就过"处理。
> **先登记**（用例名、失败率、Owner），**再归因**：按经验，等待不足和数据污染占大头，环境抖动次之，真 bug 最少但最重要。
> **重试我只对三类开**：第三方已知不稳定、有监控证实的 CI 环境抖动、已登记且定位到原因的。**绝不开全局 `--reruns`**，因为那会让所有失败都被掩盖。
> 而且**重试必须留痕**：报告里标出"这条是靠重试才过的"，每周统计 flaky 率。**如果一条用例重试三次才过，它不是通过了，它是告诉你有问题。**
> 面试可以说一句判断：**flaky 率超过 2%，这个团队就开始不信自动化了，那时再多用例也等于零。**

---

## 6. 用例分级：控制 CI 时长

| 级别 | 内容 | 频率 | 时长目标 |
| --- | --- | --- | --- |
| **冒烟**（`-m smoke`） | 登录 + 核心下单 1 条 + 支付跳转 | 每次提交 | < 15 分钟 |
| **核心回归**（`-m core`） | 主要业务流程 20~30 条 | 每天夜间 | < 1 小时 |
| **全量** | 所有 UI 用例 + 兼容性矩阵 | 每周 | 2~4 小时 |

```bash
pytest -m smoke                 # 提交级
pytest -m "core and not slow"   # 夜间
pytest                          # 全量（周末）
```

**分级的价值**：一个 3 小时的流水线没人等，最后就变成"下班前手动跑一次"或者"干脆不跑"。

---

## 7. 自查 Q8：AI 生成 UI 脚本后，人工必须检查什么

**10 条，按"最容易出错"排序：**

| # | 检查项 | AI 的典型问题 | 怎么改 |
| --- | --- | --- | --- |
| 1 | **选择器质量** | 爱用 `nth-child`、绝对 XPath、按文案匹配 | 换成 `get_by_test_id` / `get_by_role` |
| 2 | **选择器唯一性** | 给的选择器匹配到多个元素（或匹配到隐藏的那个） | 用 Playwright 的 `locator.count()` 确认是 1 |
| 3 | **断言是否存在且有意义** | 只 `assert page.url` 或断言页面标题 | 补业务断言：成功提示、数据变化、状态 |
| 4 | **有没有等待** | 要么没有等待，要么写死 `wait_for_timeout(3000)` | 换成条件等待 / `expect` 轮询 |
| 5 | **API 方法名和参数是否真实存在** | 幻觉：`page.get_by_role("button")` 参数写错、用了不存在的链式方法 | 逐个方法对照官方文档，跑一遍才信 |
| 6 | **前置状态假设** | 假设"已登录""购物车已有商品"，但脚本里没准备 | 用 fixture（`auth_page`）显式声明前置 |
| 7 | **测试数据是否硬编码** | 写死 `qa01`、写死商品名、写死订单号 | 抽到配置/fixture，用唯一数据 |
| 8 | **用例是否独立** | 写成线性脚本，后一条依赖前一条 | 每条独立成函数，用 fixture 提供状态 |
| 9 | **清理是否缺失** | 造的数据不删 | 补 teardown |
| 10 | **覆盖范围是否只有正向** | 只生成 happy path | 按六维框架补异常/边界/权限 |

**三条最重要的（时间不够就只看这三条）**：

```
① 选择器稳不稳（会不会一改版就崩）
② 断言有没有真的验证业务（还是只验证"页面打开了"）
③ 等待是不是 sleep（还是条件等待）
```

**一句话总结**：

> AI 生成 UI 脚本，等于省了"敲键盘"的时间，但**质量的三件事它都不管**：选择器稳定性、断言有效性、等待方式。所以我会把它当"初稿"而不是"代码"，**先跑一遍，再用 Trace 看它卡在哪一步** —— 通常第一步就卡在它编的选择器上。

---

## 8. 动手清单

- [ ] 把一条写在一个文件里的用例拆成 Locator / Page / Flow 三层，数一下拆完的代码行数变化。
- [ ] 配一次失败现场五件套（截图 + HTML + console + Trace），用一次真实失败验证能不能定位。
- [ ] 用 `storage_state` 把登录态复用起来，看全量耗时降多少。
- [ ] 统计最近的失败，按"等待/数据/选择器/环境/真 bug"分类，算一下 flaky 率。
- [ ] 让 AI 生成一条 UI 用例，用 §7 的 10 条清单逐条审，记录命中几条。
