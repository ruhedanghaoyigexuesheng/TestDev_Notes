# 测试开发-pytest框架篇

> 对应清单：测试框架【必须掌握】Python 部分（pytest / unittest / Mock）
> 对应自查：Q2（fixture 与 setup/teardown）、Q3（参数化数据放哪）、Q4（Mock 与 mock 第三方）
> 全篇约定：pytest 7.4 + Python 3.10。文中的 `conftest.py` 和测试文件都是能直接跑起来的完整文件，我在本机验证过。
> 立场：pytest 不是"断言库 + 跑用例"，它的价值是**用 fixture 管住所有外部资源，用参数化管住用例数量，用 hook 管住失败现场。**

---

## 0. 先定位：一个测试框架要解决的四个问题

任何接口自动化项目，本质就这四件事。pytest 分别给了对应机制：

| 问题 | pytest 的答案 | 没有它你会怎么写 |
| --- | --- | --- |
| 资源从哪来、什么时候清 | **fixture（作用域 + yield）** | 每个用例开头连 DB、结尾 close，重复且易漏 |
| 用例数量爆炸 | **参数化（parametrize）** | 复制粘贴 200 个测试函数 |
| 只跑一部分 | **mark 标签** | 手写 if 判断环境 |
| 失败后怎么复盘 | **conftest 里的 hook + 日志** | 重跑一遍看能不能复现 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| fixture（scope / yield / autouse / 依赖） | 熟练 | 整个框架的地基 |
| 参数化（含间接参数化） | 熟练 | 数据驱动的核心 |
| conftest 层级 + hook | 熟练 | 失败现场靠它 |
| mark 标签 | 会用 | CI 分片、冒烟集 |
| mock 的边界 | 熟练 | 用错会让用例失去意义 |
| unittest 存量代码 | 看得懂 | 只读不写 |
| 插件生态 | 会用 | xdist / rerun / timeout |

---

## 1. fixture：讲清楚"是什么"不如讲清楚"管什么"

### 1.1 一句话定义 + 一个真实对照

**fixture 是"声明式地准备资源，pytest 负责按作用域创建和销毁"。**

不用 fixture 的写法（新手常见）：

```python
def test_create_order_01():
    db = connect_db()            # 每条用例都写一遍
    token = login("qa01", "pwd")  # 每条用例都登录一次，慢
    try:
        ...
    finally:
        db.close()               # 忘了写就泄漏
```

用 fixture：

```python
def test_create_order_01(db, token):    # 声明需要什么，pytest 按需注入
    ...
```

三个直接收益：

1. **不重复**：登录、建库、起服务只写一次。
2. **清理可靠**：`yield` 之后的 teardown 即使用例失败也会执行。
3. **可组合**：fixture 可以依赖 fixture。

### 1.2 作用域：这是 fixture 最重要的概念

| scope | 生命周期 | 典型用途 | 用了会怎样 |
| --- | --- | --- | --- |
| `function`（默认） | 每条用例一次 | 独立测试数据、临时目录 | 最安全，但慢（每次都要准备） |
| `class` | 每个测试类一次 | 一组相关用例共享 | 少用 |
| `module` | 每个 .py 文件一次 | 文件内共享的测试数据 | 中 |
| `session` | **整个 pytest 运行一次** | 登录 token、HTTP 客户端、DB 连接池、起被测服务 | 快，但**数据要能被所有用例共用** |

**真实选择逻辑**：

```
登录 → session（只登一次，不然后面撞登录频率限制）
数据库连接 → session（连接池复用），但事务 → function（每条用例独立回滚）
测试数据 → function（每条用例自己造，避免互踩）
浏览器 driver → function（每条用例干净，脏了会互相影响）
被测服务/环境探活 → session
```

**scope 写错的两种典型症状**：

```python
# 症状 1：session fixture 依赖 function fixture → 直接报错
# ScopeMismatch: You tried to access the 'function' scoped fixture 'tmp' with a 'session' scoped request object
@pytest.fixture(scope="session")
def conf(tmp_path):      # ❌ function 级
    ...

# 症状 2：function fixture 依赖 session fixture → 数据污染
@pytest.fixture(scope="session")
def user():
    return {"id": 1, "balance": 1000}   # 所有用例共享同一个 dict，前一条用例改了余额，后一条断言就乱了

@pytest.fixture
def order(user):      # 看着是 function 级，但拿到的 user 是共享的
    user["balance"] -= 100
```

**结论**：要共享就共享"只读的、不经业务修改的"东西（token、URL、连接）；凡是会被用例改的数据，一律 function 级。

### 1.3 yield 与 addfinalizer：teardown 的两种写法

```python
@pytest.fixture
def order():
    created = api.create_order()          # setup
    yield created                          # 交出去
    api.delete_order(created["id"])        # teardown，用例失败也会执行
```

```python
@pytest.fixture
def order(request):
    created = api.create_order()
    request.addfinalizer(lambda: api.delete_order(created["id"]))   # 等价
    return created
```

两者区别（面试爱问）：

| | yield | addfinalizer |
| --- | --- | --- |
| 写法 | 简洁 | 啰嗦 |
| 能否注册多个清理 | 用 `with`/`try-finallly` 或嵌套 | 可以多次 `addfinalizer`，逆序执行 |
| setup 中途失败 | teardown 不执行 | 已注册的 finalizer **仍会执行**（更严谨） |
| 适用 | 90% 场景 | 需要动态注册清理、setup 可能半途失败 |

**teardown 里抛异常会污染结果**：如果 teardown 报错，pytest 会把用例标记为 error（不是 failed），很容易被误判为"用例挂了"。所以 teardown 里要加 try/except 并记日志：

```python
@pytest.fixture
def order():
    created = api.create_order()
    yield created
    try:
        api.delete_order(created["id"])
    except Exception as e:
        logger.warning("清理订单失败 %s: %s", created["id"], e)   # 清理失败不该让用例变 error
```

### 1.4 autouse：什么时候该用，什么时候是灾难

```python
@pytest.fixture(autouse=True)
def log_case_name(request):
    """每条用例自动打一行日志：用例名 + 开始时间。"""
    logger.info(">>> START %s", request.node.nodeid)
    yield
    logger.info("<<< END   %s", request.node.nodeid)
```

**适合 autouse 的**：日志、计时、allure 标签、统一的 mock 开关复位、断言失败信息增强。
**不适合的**：任何有副作用的业务准备（起服务、造数据）。因为你看不出某条用例依赖了它，排查时非常痛苦。

规则：**autouse 只做"观察"和"复位"，不做"准备"。**

### 1.5 参数化 fixture 与间接参数化

两种"参数化"，用途不同，面试区分清楚就能加分：

```python
# ① parametrize：参数化"用例"，一条数据 = 一条用例
@pytest.mark.parametrize("num,expected", [(1, 0), (0, 400), (-1, 400)])
def test_add_cart(api, num, expected):
    assert api.post("/api/cart", json={"num": num}).json()["code"] == expected

# ② fixture 的 params：参数化"资源"，同一个 fixture 换不同实例
@pytest.fixture(params=["alipay", "wechat"], ids=["支付宝", "微信"])
def pay_channel(request):
    return request.param

def test_pay(api, pay_channel):
    # 会跑两次，pay_channel 分别是 alipay / wechat
    ...
```

```python
# ③ 间接参数化：数据要经过 fixture 加工（最常见于"用不同账号登录"）
@pytest.fixture
def client(request):
    user = request.param                 # 从参数里拿账号
    token = login(user)
    return ApiClient(BASE, token)

@pytest.mark.parametrize("client", ["admin", "guest"], indirect=True)
def test_permission(client):
    ...
```

### 1.6 一份能直接用的 conftest.py

```python
# tests/conftest.py
import logging
import time

import pytest
import requests

BASE = "http://127.0.0.1:5057"      # 真实项目从配置读，见工程习惯篇
logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def base_url():
    """环境地址。抽成 fixture：换环境只改一处，用例里不出现硬编码 URL。"""
    return BASE


@pytest.fixture(scope="session")
def api(base_url):
    """全局 HTTP 客户端：整个会话复用连接和登录态。

    scope=session 的理由：登录一次就够，避免撞登录频率限制；连接复用省握手。
    """
    s = requests.Session()
    s.headers.update({"User-Agent": "qa-autotest/1.0"})
    r = s.post(f"{base_url}/api/login", json={"user": "qa01", "pwd": "p"}, timeout=(3, 10))
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    logger.info("登录成功 user=qa01")
    yield s
    s.close()


@pytest.fixture
def fresh_order(api, base_url):
    """每条用例一个独立订单，用完删掉。scope=function 保证用例之间不互踩。"""
    r = api.post(f"{base_url}/api/orders", json={"sku_id": 1001, "num": 1}, timeout=(3, 10))
    r.raise_for_status()
    order = r.json()["data"]
    yield order
    try:
        api.delete(f"{base_url}/api/orders/{order['order_id']}", timeout=(3, 10))
    except Exception as e:
        logger.warning("清理订单失败 %s: %s", order["order_id"], e)


@pytest.fixture(autouse=True)
def case_timer(request):
    """每条用例自动计时并打日志。只做观察，不做准备。"""
    logger.info(">>> START %s", request.node.nodeid)
    start = time.perf_counter()
    yield
    logger.info("<<< END   %s cost=%.3fs", request.node.nodeid, time.perf_counter() - start)
```

### 1.7 fixture 在 xdist 下的坑

`pytest -n 4` 时，**每个 worker 是独立进程，session 级 fixture 每个 worker 各执行一次**。后果：

- 登录 4 次（不是 1 次）→ 可能触发登录限制。
- 每个 worker 拿到的"共享数据"不同 → 不要用 session fixture 做"全局唯一 ID 生成器"。
- 起被测服务：4 个 worker 抢同一个端口 → 必然失败。

解法：用文件/外部服务做跨进程协调，或用 `pytest-xdist` 的 worker id 做隔离：

```python
@pytest.fixture(scope="session")
def account(worker_id):
    """每个 worker 用自己的账号，避免登录互踢。"""
    return f"qa_{worker_id}"        # worker_id 由 xdist 提供，串行时是 "master"
```

---

## 2. 参数化：数据放哪，是工程判断不是口味

### 2.1 三种参数化形态

```python
import pytest

# ① 内联：字段少、用例少、要一眼看到期望值
@pytest.mark.parametrize("num, expected_code", [
    (1, 0),
    (0, 400),
    (-1, 400),
], ids=["正常", "数量为0", "数量为负"])
def test_add_cart(api, base_url, num, expected_code):
    resp = api.post(f"{base_url}/api/cart", json={"num": num})
    assert resp.json()["code"] == expected_code, resp.text


# ② 笛卡尔积：多个维度组合（注意数量爆炸）
@pytest.mark.parametrize("channel", ["alipay", "wechat"])
@pytest.mark.parametrize("amount", [0.01, 100, 99999])
def test_pay(api, base_url, channel, amount):
    resp = api.post(f"{base_url}/api/pay", json={"channel": channel, "amount": amount})
    assert resp.json()["code"] == 0, resp.text      # 2 × 3 = 6 条用例


# ③ 从文件读：用例多、要给人维护、要复用
import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

def load_cases():
    with open(DATA_DIR / "cart_cases.csv", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["case_name"])
def test_add_cart_from_file(api, base_url, case):
    resp = api.post(f"{base_url}/api/cart", json={"num": int(case["num"])})
    assert resp.json()["code"] == int(case["expected_code"]), resp.text
```

### 2.2 数据放哪：三个地方的决策表（自查 Q3 的答案）

| 放哪 | 适合 | 不适合 | 代价 |
| --- | --- | --- | --- |
| **代码里内联** | 逻辑型用例（分支、状态流转）、参数少于 10 组、要 code review 看逻辑 | 数据型用例（几百组等价类） | 加用例要改代码 → 要走 PR → 慢 |
| **文件里（YAML/CSV/JSON/excel）** | 数据型用例、需要非开发同学维护、同一份数据给多套脚本用 | 含复杂逻辑、需要动态计算的数据 | 文件格式要校验，写错了报错不直观 |
| **命令行 / 环境变量传入** | 环境相关（base_url、账号、并发数）、CI 里换参数、临时调试 | 大量用例数据（命令行装不下） | 只适合少量标量 |
| **数据库 / 接口动态拉取** | 用例数据本身在系统里（"所有在售商品"）、要跟线上数据同步 | 结果不可控、用例不稳定 | 需要数据源可靠，否则用例随机失败 |

**我的实际做法（可以直接抄）**：

```
tests/
├── conftest.py          # 环境、连接、通用 fixture
├── data/
│   ├── env.yaml         # 环境地址、账号（按环境分）
│   └── cart_cases.csv   # 用例数据（非开发同学也能加）
└── test_cart.py         # 放逻辑和断言
```

- **环境地址/账号** → `env.yaml` + 环境变量覆盖（配置文件只管默认值，CI 用 `-e` 或 env 覆盖）。
- **用例数据（会不断新增的）** → CSV，给测试同学维护。
- **有分支逻辑的用例** → 内联在代码里，因为逻辑本身就是被测对象。

### 2.3 参数化的坑

| 坑 | 现象 | 解法 |
| --- | --- | --- |
| id 是中文乱码 | 报告里显示 `\u6b63\u5e38` | 用 `ids=` 显式指定，或在 `pytest.ini` 里配 `disable_test_id_escaping_and_forfeit_all_rights_to_community_support = True`（能用但有风险，更推荐显式 ids） |
| 参数化里有可变对象 | `[{"a": []}]` 被多条用例共享，用例 1 改了影响用例 2 | 用 `factory` 生成，或在用例里 copy |
| 组合爆炸 | 3 个维度各 10 个值 = 1000 条 | 用 pairwise 抽样，或精选边界值 |
| 参数和 fixture 同名 | 冲突报错 | 改参数名，或用 `indirect` |
| 数据文件路径 | CI 里 `open("data/x.csv")` 找不到 | `Path(__file__).parent / "data" / ...` |

---

## 3. mark 标签：让 CI 分片跑

```python
# tests/test_order.py
import pytest

@pytest.mark.smoke
def test_create_order(api, fresh_order):
    ...

@pytest.mark.slow
def test_full_payment_flow(api):
    ...

@pytest.mark.skipif(not os.getenv("TEST_ISOLATED_ENV"), reason="需要独立环境，CI 主流程不跑")
def test_chargeback(api):
    ...
```

```bash
pytest -m smoke                      # 只跑冒烟
pytest -m "not slow"                 # 排除慢用例
pytest -m "smoke and not slow"       # 组合
pytest -m "p0 or p1"                 # 优先级
```

**必须注册 marker**，否则拼错会静默不生效（最容易踩的坑）：

```ini
# pytest.ini
[pytest]
markers =
    smoke: 冒烟用例，每次提交都跑
    slow: 超过 30s 的用例
    p0: 最高优先级
addopts = -ra --strict-markers
testpaths = tests
```

`--strict-markers` 会让未注册的 marker 直接报错 —— **这就是防"拼错静默不生效"的手段，建议永远开着。**

`skip` / `skipif` / `xfail` / `xpass` 的区别：

| 标记 | 含义 | 结果 |
| --- | --- | --- |
| `skip` | 无条件跳过 | skipped |
| `skipif(条件)` | 条件成立跳过 | skipped |
| `xfail` | 预期失败 | 失败了算 xfailed（通过），**意外通过算 xpassed（默认不算失败，容易掩盖 bug）** |
| `xfail(strict=True)` | 预期失败 | 意外通过算 failed → **推荐用 strict** |

> 用 `xfail(strict=True)`，因为"标记为预期失败的 bug 被悄悄修复了"这件事也需要知道。

---

## 4. conftest 与 hook：失败现场全靠这里

### 4.1 层级

```
tests/
├── conftest.py              # 对 tests/ 下所有用例生效
├── api/
│   ├── conftest.py          # 只对 api/ 生效，可覆盖上层的同名 fixture
│   └── test_order.py
└── ui/
    ├── conftest.py          # 只对 ui/ 生效
    └── test_login.py
```

规则：

1. **就近优先**：子目录的 conftest 里定义同名 fixture，会覆盖父目录的。
2. **fixture 不需要 import**，pytest 自动发现（同层及上层）。
3. **conftest 不放业务用例**，只放 fixture 和 hook。

### 4.2 三个必用的 hook

```python
# tests/conftest.py
import os

import pytest


# ① 失败时自动落盘请求/响应/截图（接口自动化最有用的一段代码）
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    # 只在用例主体（call）失败时动作，setup/teardown 失败不重复处理
    if report.when != "call" or not report.failed:
        return

    # 用例里如果有 api fixture，把最后一次响应落盘
    api = item.funcargs.get("api")
    if api is not None and getattr(api, "last_response", None) is not None:
        from framework.artifacts import dump_failure
        # ⚠️ nodeid 形如 tests/test_order.py::test_create[正常]，含 "::" 和 "/"。
        # Windows 文件名不允许 ":"，不清洗会 OSError: Invalid argument ——
        # 典型现象是"Linux CI 正常，本地 Windows 跑一定炸"。
        safe = item.nodeid.replace("::", "_").replace("/", "_").replace("\\", "_")
        path = dump_failure(api.last_response, safe, ARTIFACT_DIR)
        report.sections.append(("失败现场", f"已保存: {path}"))


# ② 按标签排序：冒烟先跑，慢的最后（失败了能快速反馈）
def pytest_collection_modifyitems(config, items):
    items.sort(key=lambda i: (0 if i.get_closest_marker("smoke") else 1))


# ③ 动态跳过：环境不支持就跳过，而不是让它失败。
#    ⚠️ 注意：② 和 ③ 都用 pytest_collection_modifyitems 时只能定义一个（同名函数互相覆盖），
#    要写进同一个函数里。而且任何 pytest_ 开头的函数都会被当成 hook 校验，
#    名字拼错会直接 PluginValidationError: unknown hook ...，整个会话起不来 —— 这个坑很常见。
def pytest_collection_modifyitems(config, items):
    # 先排序
    items.sort(key=lambda i: (0 if i.get_closest_marker("smoke") else 1))
    # 再动态跳过
    if not os.getenv("HAVE_DEVICE"):
        for item in items:
            if "device" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="没有可用真机"))
```

**`report.sections.append(...)` 这行的价值**：失败信息会出现在 HTML 报告里，不用去翻日志文件夹找。

### 4.3 用例结果流转（排查"为什么显示 error 不是 failed"）

```
setup 阶段失败 → error（比如 fixture 里登录挂了）
call 阶段失败  → failed（断言失败，正常）
teardown 失败  → error（清理失败，容易误判）
```

`pytest_runtest_makereport` 里的 `report.when` 就是这三个值。**看到 error 先想到"不是断言挂了，是准备或清理挂了"**，这个判断能省很多时间。

### 4.4 常用的其他 hook

| hook | 用途 |
| --- | --- |
| `pytest_generate_tests` | 自定义参数化（从数据库/接口动态生成用例） |
| `pytest_configure` | 启动时读配置、注册 marker |
| `pytest_sessionfinish` | 收尾：生成汇总、上报结果 |
| `pytest_runtest_logreport` | 实时上报（对接测试平台时用） |

---

## 5. 插件生态：装这五个就够

```bash
pip install pytest-xdist pytest-html pytest-rerunfailures pytest-timeout pytest-mock
```

| 插件 | 作用 | 用法 | 注意 |
| --- | --- | --- | --- |
| `pytest-xdist` | 多进程并行 | `-n 4 --dist loadscope` | 见 1.7 的坑 |
| `pytest-html` / `allure-pytest` | 报告 | `--html=report.html --self-contained-html` | allure 功能强但要起服务 |
| `pytest-rerunfailures` | 失败重跑 | `--reruns 2 --reruns-delay 3` | **会掩盖真 bug**，只能用于已知的 flaky 用例 |
| `pytest-timeout` | 单用例超时 | `--timeout=120 --timeout-method=thread` | 防"用例挂死拖死 CI" |
| `pytest-mock` | `mocker` fixture | 见第 7 节 | 比裸 `unittest.mock` 好写 |

**关于重跑的态度**（这是工程判断，不是配置问题）：

重跑是"止疼药"不是"消炎药"。允许重跑的三类场景：

1. 第三方的已知不稳定（短信、支付回调）。
2. 环境抖动，有监控证实。
3. 已知 flaky 且已登记缺陷。

**绝不允许**：为了让流水线变绿而全局开启重跑。那样你测的是"重跑三次能不能过"，不是"功能对不对"。

其他实用参数：

```bash
pytest -x                      # 第一个失败就停（本地调试）
pytest --lf                    # 只跑上次失败的（复盘神器）
pytest --ff                    # 先跑上次失败的
pytest -k "order and not cancel"  # 按名字筛选
pytest -v --durations=10       # 列出最慢的 10 条用例
pytest --tb=short              # 简洁堆栈
```

`--lf`（last-failed）是日常最高频的参数，配合 `.pytest_cache` 用。

---

## 6. unittest 存量代码：看得懂就行

老项目常见，读的时候认这几样：

```python
import unittest
from unittest.mock import patch

class TestOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):          # 整个类一次
        cls.db = connect()

    def setUp(self):              # 每条用例一次
        self.token = login()

    def tearDown(self):
        cleanup()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_create(self):
        resp = request_order(self.token)
        self.assertEqual(resp.status_code, 200)     # 注意断言是 assertXxx
        self.assertIn("code", resp.json())

    def test_with_mock(self):
        with patch("module.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            ...
```

对照表，读旧代码时不用查：

| unittest | pytest |
| --- | --- |
| `setUpClass / tearDownClass` | `fixture(scope="class"/"module")` |
| `setUp / tearDown` | `fixture`（默认 function） |
| `self.assertEqual(a, b)` | `assert a == b` |
| `self.assertIn(x, y)` | `assert x in y` |
| `self.assertRaises(E)` | `with pytest.raises(E):` |
| `self.assertRaisesRegex(E, r"xx")` | `with pytest.raises(E, match="xx"):` |
| `skipTest()` | `pytest.skip()` |
| `subTest()` | `@pytest.mark.parametrize` |

pytest **能直接收集并运行 unittest 写的 TestCase**，所以迁移可以渐进：新用例用 pytest 风格，老的不动，共用一个 `pytest.ini`。

---

## 7. Mock（自查 Q4）

### 7.1 先想清楚：mock 不是"造假数据"，是"切断真实依赖"

**四类需要 mock 的第三方依赖**（自查 Q4 的核心答案）：

| 场景 | 为什么必须 mock | 例子 |
| --- | --- | --- |
| **不稳定/不可控** | 真实第三方挂了、限流了，你的用例就红了，但错不在被测系统 | 短信、支付回调、地图、人脸识别 |
| **无法造出异常场景** | 你想测"支付超时""回调重复""返回 500"，真实第三方不会配合你 | 测降级、测重试、测熔断 |
| **有成本/配额** | 真实调用要钱或有限额，跑 1000 次用例不能真扣 1000 次 | 支付、短信、实名认证 |
| **未就绪/隔离环境** | 下游还没开发完、测试环境不让连外网 | 新接口联调、内网隔离 |

**三类绝对不要 mock 的东西**：

1. **被测服务本身**：mock 掉它，你就只是在测自己的假数据。
2. **你要验证的集成点**：如果需求就是"和支付网关对接正确"，那不能 mock，要用沙箱环境。
3. **断言要用的真实响应**：mock 返回的数据是你自己编的，断言它等于自证。

一句话原则：**mock 边界，不 mock 逻辑。**

### 7.2 三种实现，按场景选

```python
# ① 单元测试用：unittest.mock.patch（进程内替换）
from unittest.mock import patch

def pay(order):
    return requests.post("https://pay.third.com/api/pay", json={"order": order}, timeout=10)

def test_pay_timeout():
    with patch("requests.post", side_effect=requests.exceptions.Timeout):
        with pytest.raises(requests.exceptions.Timeout):
            pay("20261028001")
```

```python
# ② pytest 内置的 monkeypatch：改环境变量、改属性、改函数
def test_env(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr("framework.config.BASE_URL", "http://127.0.0.1:5057")
    assert os.getenv("ENV") == "test"
```

```python
# ③ pytest-mock 的 mocker fixture：自动清理，写法更短（需 pip install pytest-mock）
def test_pay_error(mocker):
    mocker.patch("requests.post").return_value.status_code = 500
    ...
```

**patch 路径这个坑一定要讲清**：

```python
# 你的模块 myapp/order.py 里这样导入
from requests import post
def pay():
    return post(url)

# ✅ 正确：patch 你的模块里的那个名字（"使用处"）
mocker.patch("myapp.order.post")

# ❌ 错误：patch 源头的 requests.post（你的模块已经 import 了引用，改源头没用）
mocker.patch("requests.post")
```

规则：**patch 的是"被测代码看到的那份引用"**，即 `patch("被测模块.import的名字")`。

### 7.3 接口自动化里 mock 第三方：用 mock server，不要用 patch

这是本节的**核心工程判断**，很多人的写法是错的：

| 目标 | 用什么 | 原因 |
| --- | --- | --- |
| 测**你写的函数**里的逻辑 | `mock.patch` 进程内替换 | 快、隔离 |
| 测**被测服务的 HTTP 行为**（超时/重试/降级） | **独立 mock server** | 你的测试进程和被测服务是两个进程，patch 不到对方 |
| 第三方返回固定数据联调 | mock server 或沙箱环境 | 可控、可记录 |

为什么"用 patch mock 第三方"在接口自动化里行不通：你的 pytest 进程里 patch 的是自己的 `requests` 调用，而被测服务（Java/Python 服务）是另一个进程，它调第三方的时候你根本管不到。**这时候必须起一个假的第三方服务，然后把被测服务的配置指向它。**

```python
# tests/conftest.py
import threading
import time

import pytest
from flask import Flask, jsonify, request


def make_mock_pay_server():
    """一个假的支付网关。可以通过 /admin/mode 动态切换行为。"""
    app = Flask("mock_pay")
    state = {"mode": "success", "hits": []}

    @app.post("/api/pay")
    def pay():
        state["hits"].append(request.json)
        mode = state["mode"]
        if mode == "timeout":
            time.sleep(35)                       # 模拟超时
            return jsonify({"code": 0})
        if mode == "error":
            return jsonify({"code": 500, "msg": "内部错误"}), 500
        if mode == "duplicate":
            return jsonify({"code": 0, "trade_no": "T-DUP"})
        return jsonify({"code": 0, "trade_no": "T-20261028001"})

    @app.post("/admin/mode")
    def set_mode():
        state["mode"] = request.json["mode"]
        return {"ok": True, "mode": state["mode"]}

    @app.get("/admin/hits")
    def hits():
        return {"count": len(state["hits"]), "data": state["hits"]}

    return app, state


@pytest.fixture(scope="session")
def mock_pay():
    app, state = make_mock_pay_server()
    t = threading.Thread(target=app.run, kwargs={"port": 5058, "debug": False, "use_reloader": False},
                         daemon=True)
    t.start()
    time.sleep(1.5)                    # 等端口起来（生产代码用重试探活，别 sleep 硬等）
    yield state
    state["mode"] = "success"          # 复位，防止污染下一个用例
```

用法：

```python
def test_pay_timeout_and_retry(mock_pay, api):
    mock_pay["mode"] = "timeout"                  # 让第三方超时
    r = api.post("/api/order/pay", json={"order_id": "20261028001"})
    assert r.json()["code"] != 0                   # 业务应返回明确失败
    assert r.elapsed.total_seconds() < 15          # 不应等满 35s，说明超时生效
```

**这套夹具的价值**：能测"超时/重试/熔断/降级"这些**只能靠注入故障才能验证**的行为，而这些恰恰是线上事故的高发区。

### 7.4 mock 的三个反模式

```python
# ❌ 反模式 1：mock 掉被测对象 → 你测了个寂寞
mocker.patch("myapp.order.create_order")
test_create_order()      # 断言的是 mock，不是真实逻辑

# ❌ 反模式 2：mock 返回的数据和真实结构不一致 → 用例绿，联调挂
mocker.patch("requests.post").return_value.json.return_value = {"ok": True}
# 真实接口返回 {"code":0,"data":{"id":1}}，你的断言却在检查 "ok"

# ❌ 反模式 3：mock 泄漏到其他用例 → 随机失败
# 用 with 或 mocker（自动清理），别手工 patch_start 之后忘了 stop
```

---

## 8. 自查清单逐条作答（Q2–Q4）

### Q2. pytest 的 fixture 是干什么的？setup/teardown 场景你会怎么用？

**fixture 是资源管理机制**：声明"这条用例需要什么"，pytest 按 `scope` 决定创建几次、什么时候销毁。它替代了 unittest 的 `setUp/tearDown`，但更强：可以跨模块共享（conftest）、可以互相依赖、可以参数化、可以按需注入（用不到就不创建）。

**setup/teardown 场景怎么用，按生命周期分**：

| 场景 | 用什么 |
| --- | --- |
| 全局只做一次（登录、起服务、连接池、环境探活） | `scope="session"` + yield |
| 每个测试文件一次（加载该文件的测试数据） | `scope="module"` |
| **每条用例独立准备和清理（造订单、开浏览器、开事务）** | `scope="function"`（默认）+ yield |
| 每条用例都要做、且与业务无关（计时、日志、mock 复位） | `autouse=True` + 只做观察/复位 |
| 清理必须执行且 setup 可能失败 | `request.addfinalizer` |

一个具体例子（这是我在项目里的真实分层）：

```python
@pytest.fixture(scope="session")
def api():            # 一次登录，全局复用
    ...

@pytest.fixture
def fresh_order(api):  # 每条用例一个独立订单，用完删除
    order = create()
    yield order
    delete(order)
```

**要说出"为什么这样分"**，这比背 API 重要：session 是为了快（登录只一次），function 是为了隔离（数据不互踩）。**共享的是"不会变的资源"，隔离的是"会被改的数据"。**

### Q3. 参数化数据放在哪里？文件里、代码里还是命令行传入？各自的适用场景？

见 §2.2 决策表。**30 秒口头版**：

> 分三类放。
> **环境相关的东西（地址、账号、并发数）** → 配置文件 + 环境变量/命令行覆盖，因为同一份代码要跑多环境。
> **用例数据（几百组等价类）** → CSV/YAML 文件，因为要能持续新增，而且希望非开发同学也能维护。
> **有逻辑的用例（状态流转、分支）** → 内联在代码里，因为逻辑本身是被测对象，必须能 code review。
> 判断标准一句话：**数据会增长就外置，逻辑在变化就内联，环境会切换就走配置。**

### Q4. Mock 是什么？什么情况下接口自动化需要 mock 第三方依赖？

**Mock 是用可控的假实现替换真实依赖**，目的是让测试聚焦在被测逻辑上，并获得"能造任意响应"的能力。

**接口自动化需要 mock 第三方的四种情况**（见 §7.1 表格）：不稳定、造不出异常场景、有成本/配额、未就绪或网络隔离。

**但要说清两个边界**，这是区分水平的地方：

1. **mock 的是边界，不是被测逻辑**。mock 支付网关是合理的；mock 自己的下单服务就没意义了。
2. **接口自动化里 mock 第三方要用独立 mock server，不能用进程内 patch**。因为被测服务和测试进程是两个进程，patch 不到对方。能测超时/重试/熔断/降级，靠的就是这个 mock server 能注入故障。

---

## 9. 复习动作清单

- [ ] 把你们项目里的 `conftest.py` 按 §1.6 的结构重写一遍：session 级客户端 + function 级数据 + autouse 日志。
- [ ] 加一条 `pytest_runtest_makereport` hook，让失败用例自动落盘请求/响应（代码在 §4.2）。
- [ ] 在 `pytest.ini` 里加 `--strict-markers`，跑一次，看有没有拼错的 marker 暴露出来。
- [ ] 把一组重复的中文 id 加进参数化，确认报告里显示正常。
- [ ] 用 §7.3 的 mock server 写一条"第三方超时"的用例，验证你们系统的超时和降级。
- [ ] 跑 `pytest --durations=10`，找出最慢的 10 条用例，看是不是 fixture 太重。
