# 测试开发-接口Mock与安全篇

> 对应清单：Mock 与依赖隔离【必须掌握（概念 + 动手一次）】+ 安全测试入门【必须掌握（基础项）】+ AI 在接口测试中的用法【必须掌握】
> 对应自查：Q3（支付回调何时 Mock、何时必须真调、怎么同步）、Q6（水平越权用例怎么写、自动化怎么覆盖）、Q9（审查 AI 生成用例的清单）
> 说明：水平/垂直越权的**定义和基础用例**在《测试流程与方法论篇》§4 已讲，本篇只讲**自动化怎么覆盖**；Mock 的代码层用法在《pytest框架篇》§7，本篇讲**接口级的 Mock**。

---

## 0. 先定位：三件事各自解决什么

| 能力 | 解决什么 | 判断标准 |
| --- | --- | --- |
| Mock | 依赖不可控时，测试还能往下做 | 能不能造出"第三方超时/500/重复回调" |
| 安全用例 | 功能之外的攻击面 | 换身份、改参数，还能不能拿到不该拿的 |
| AI 辅助 | 用例产出效率 | 生成的初稿，你要能说出它漏了什么 |

---

# 第一部分：Mock 与依赖隔离

## 1. 三类必须 Mock 的场景（清单已给，这里说清"为什么"）

| 场景 | 为什么必须 | 具体例子 |
| --- | --- | --- |
| **不稳定 / 没有测试环境** | 真调会让你的用例失败，但错不在被测系统 | 短信网关（限流、收费、测试号码白名单）、支付回调、风控、第三方登录 |
| **异常注入** | 正常环境造不出故障，而故障路径才是高发区 | 超时、500、重复回调、返回畸形报文、慢响应 |
| **契约先行** | 对方还没开发完，你不想等 | 新对接的物流接口，按文档先 Mock 出用例 |

**核心认知**：Mock 的目的不是"让用例变绿"，**是"让不可控变成可控"**。判断要不要 Mock，问一句：**这个依赖的失败，是不是我这次想测的东西？** 不是 → Mock；是 → 必须真调。

## 2. 三层工具，按场景选（清单给的三个层次）

| 层次 | 工具 | 适合 | 不适合 |
| --- | --- | --- | --- |
| **工具层** | Apifox / Postman 内置 Mock | 给前端联调供数、手工测试造数据 | 无法进 CI、不能编程控制 |
| **服务层** | WireMock / moco / Flask 自建 | **自动化框架 + CI 里隔离第三方** | 需要维护服务 |
| **代码层** | pytest-mock / unittest.mock | 单测里 mock 函数、SDK | **跨进程无效**（见下） |

**最关键的一条认知**（很多人在这里犯错）：

> **接口自动化里 mock 第三方，必须用"服务层"（起一个假服务），不能用"代码层"（patch 函数）。**
> 因为你的 pytest 进程和被测服务是两个进程，你 patch 的是自己进程里的 `requests`，管不到被测服务调第三方。

## 3. 服务层 Mock 动手（Flask 版，和《pytest框架篇》§7.3 同源）

```python
# mock_server/pay_gateway.py —— 模拟第三方支付网关
import time

from flask import Flask, jsonify, request

app = Flask("mock_pay")
STATE = {"mode": "success", "hits": [], "callbacks": []}


@app.post("/pay/api/create")
def create_pay():
    """下单支付：返回支付单号，供被测服务调用。"""
    body = request.get_json(silent=True) or {}
    STATE["hits"].append(body)
    if STATE["mode"] == "timeout":
        time.sleep(35)                      # 触发被测服务的读超时
        return jsonify({"code": 0})
    if STATE["mode"] == "error":
        return jsonify({"code": 500, "msg": "网关内部错误"}), 500
    return jsonify({"code": 0, "trade_no": "MOCK-" + str(len(STATE["hits"]))})


@app.post("/pay/api/callback")
def callback():
    """支付回调：模拟第三方主动通知被测服务。"""
    payload = request.get_json(silent=True) or {}
    STATE["callbacks"].append(payload)
    return jsonify({"code": 0})


# ── 控制面：给测试用，动态切换行为 ─────────────────
@app.post("/admin/mode")
def set_mode():
    STATE["mode"] = request.json["mode"]
    return {"ok": True, "mode": STATE["mode"]}


@app.get("/admin/calls")
def calls():
    """看被测服务到底调了几次、传了什么（验证重试次数、幂等）。"""
    return {"count": len(STATE["hits"]), "data": STATE["hits"]}


@app.post("/admin/reset")
def reset():
    STATE.update({"mode": "success", "hits": [], "callbacks": []})
    return {"ok": True}
```

```python
# tests/conftest.py
import threading
import time

import pytest


@pytest.fixture(scope="session")
def mock_pay():
    from mock_server.pay_gateway import app
    threading.Thread(target=lambda: app.run(port=5058, debug=False, use_reloader=False),
                     daemon=True).start()
    time.sleep(1.5)
    yield "http://127.0.0.1:5058"
```

**被测服务的配置指向这个 mock**（在测试环境改下游地址，或启动被测服务时通过环境变量注入）：

```bash
PAY_GATEWAY_URL=http://127.0.0.1:5058/pay python -m app.main
```

**这套东西能测的东西，是真实第三方永远给不了你的**：

| 能测的 | 怎么用 |
| --- | --- |
| 下游超时，服务是否快速失败 | `mode=timeout` |
| 下游 500，是否触发重试/熔断 | `mode=error` |
| 重试了几次 | `GET /admin/calls` 看 count |
| 回调重复，是否重复入账 | 连发 3 次 `POST /pay/api/callback` |
| 回调乱序（先成功后失败） | 手动按序发不同状态的 callback |
| 契约变更（少字段/多字段） | 改 mock 的返回结构 |

## 4. 两条纪律（清单给的两条，展开怎么落地）

### 纪律一：Mock 了什么必须可见

```python
import pytest

@pytest.mark.mocked("pay_gateway", reason="第三方沙箱不稳定，见 JIRA-123")
def test_pay_with_mock(mock_pay, api, base_url):
    ...
```

```python
# 在 conftest 里把这些标记收集到报告
def pytest_collection_modifyitems(config, items):
    for item in items:
        marks = [m for m in item.iter_markers(name="mocked")]
        if marks:
            item.add_marker(pytest.mark.skipif(False, reason=""))  # 占位，实际用 allure 标签
```

实际最简单的做法（不搞花活）：

1. **用例名带 `mocked`**：`test_pay_mocked_timeout`。
2. **Allure 标签**：`allure.dynamic.tag("MOCK")`。
3. **报告顶部汇总一句**：本次运行有 N 条用例走 mock。

**为什么必须可见**：半年后有人看"全绿"的报告，以为是真实链路验证过了 —— **一个隐形的 mock 比一个失败的用例更危险。**

### 纪律二：Mock 要跟契约同步

| 做法 | 具体 |
| --- | --- |
| **从 OpenAPI 生成 stub** | WireMock 支持从 spec 生成 stub；Apifox 从文档生成 Mock。**改文档 = 改 Mock** |
| **定期对比** | 每周跑一次"真实沙箱 vs mock"的响应结构对比，差异报警 |
| **保留真调用例兜底** | 关键链路（如支付成功、退款）保留 1~2 条**真实调用**的用例，每天跑一次 |
| **CI 门禁** | 文档变更的 PR 必须同步更新 mock 文件（可加检查脚本） |

## 5. 自查 Q3 完整作答：支付回调，何时 Mock、何时必须真调

### 什么时候 Mock

| 情况 | 判断依据 |
| --- | --- |
| 第三方没有测试环境 / 沙箱不稳定 | 每次跑用例都因第三方挂而失败 |
| 要测**自己的**异常处理（超时/重试/熔断/降级） | 这些场景真实第三方永远给不了你 |
| 要测**重复回调**的处理（幂等） | 需要手动重放同一个 callback |
| 高频回归（每天几十次） | 真调有成本、有配额、有延迟 |
| 联调前期，对方接口还没上线 | 契约先行 |

### 什么时候必须真调

| 情况 | 为什么 |
| --- | --- |
| **上线前验收 / 大版本回归** | Mock 只能证明"我的逻辑对"，不能证明"能对上真实对方" |
| **验证对接正确性**：签名、报文格式、编码、证书 | Mock 是你写的，天然符合你自己的假设，测不出"你以为的格式"和"真实格式"的差异 |
| **资金相关链路**（支付、退款、对账） | 沙箱环境真调一次，确认全链路通 |
| **契约发生变更后** | 对方升级了 API 版本，必须真调确认 |
| **每日一次的兜底巡检** | 保留 1~2 条真实链路用例，防止 mock 长期脱节 |

### 一句话总结（答题用）

> **测"我的处理逻辑"用 Mock，测"我和对方的对接"必须真调。**
> 支付回调这种依赖，我会用 Mock 覆盖超时、500、重复回调、乱序这些异常分支（这些只有 Mock 能造），同时保留 1~2 条真实沙箱的用例每天跑一次，用来校验契约没变。

### 怎么保持 Mock 与文档同步（这是加分点）

> 三个机制：
> **① 从文档生成**：mock 的响应结构不从手写开始，从 OpenAPI 生成，改文档等于改 mock。
> **② 契约对比**：每周跑一次"真实沙箱响应 vs mock 响应"的结构 diff，字段多了少了都报警。这个脚本很简单，用《数据结构与算法篇》的 `diff_keys` 就行。
> **③ 真调用例兜底**：关键链路保留真调用例，每天定时跑。**如果真调用例和 mock 用例的结论不一致，优先信真调的那个。**

## 6. Mock 的三个反模式

| 反模式 | 问题 |
| --- | --- |
| Mock 掉被测服务本身 | 你测的是自己编的数据 |
| Mock 返回结构和真实不一致，且没人发现 | 全绿的报告是假的 |
| 用代码层 patch 去 mock 跨进程的第三方 | 根本没生效，用例"通过"是因为压根没调 |

---

# 第二部分：安全测试入门

## 7. 五类必测（对应 OWASP 常见项）

| 类型 | 测什么 | 探测用例 |
| --- | --- | --- |
| **越权** | 水平：看别人数据；垂直：做高权限操作 | 见 §8 |
| **注入** | SQL 注入、命令注入 | `' OR '1'='1`、`1; DROP TABLE`、`${jndi:ldap://...}` |
| **敏感信息** | 响应泄露密码哈希、手机号明文、堆栈、内部 IP | 检查每个响应的字段和错误信息 |
| **重放与频率** | 无时间戳裸重放、短信/验证码频率限制 | 同一请求发 100 次；同一手机号连发 20 条短信 |
| **传输** | 敏感接口是否强制 HTTPS | `http://` 访问是否被拒/跳转；抓包看是否明文 |

**注入用例的正确期望**：不是"能登进去"，而是"**参数被正确转义，返回参数错误或查不到，且数据库没被破坏**"。

```python
@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "'; DROP TABLE orders; --",
    "1' UNION SELECT password FROM users --",
    "admin'--",
])
def test_sql_injection(api, base_url, payload):
    r = api.get(f"{base_url}/api/orders", params={"order_no": payload})
    assert r.status_code in (400, 404, 422), f"注入载荷返回异常状态: {r.status_code}"
    assert "sql" not in r.text.lower(), "错误信息泄露了 SQL 细节"
    # 关键：注入后表还在（不是只看返回码）
    assert db.query_one("SELECT COUNT(*) c FROM orders")["c"] > 0, "表被删了！"
```

**"表还在"这条断言是灵魂** —— 只断言返回码，测不出真实的注入伤害。

## 8. 自查 Q6 完整作答：水平越权用例 + 自动化覆盖

**定义部分简述**（详细见《测试流程与方法论篇》§4）：水平越权 = 同角色访问别人的数据；垂直越权 = 低权限做高权限的事。

### 8.1 用例怎么写（三个要素）

```
前置：用户 A、用户 B 各有一条自己的资源（订单 O-A、O-B）
操作：A 的 token 请求 B 的资源
断言：403 或 404（按团队约定），且响应体里不能包含 B 的任何数据
```

```python
def test_horizontal_a_cannot_read_b_order(api_a, api_b, base_url, order_b):
    resp = api_a.get(f"{base_url}/api/orders/{order_b['order_no']}")
    assert resp.status_code in (403, 404), f"水平越权: A 能读 B 的订单 {resp.text[:300]}"
    assert order_b["order_no"] not in resp.text, "响应体泄露了资源内容"
```

**两个容易漏的点**：

1. **断言响应体不含对方数据**：有些系统返回 200 + 空 data，看起来"没越权"，但某些字段仍带出了对方 ID。
2. **测所有入口**：路径参数、query 参数、body 字段、批量接口、导出接口。

### 8.2 自动化怎么覆盖（这是 Q6 的核心）

**核心思路：把"角色 × 接口"做成矩阵，用参数化跑遍。**

```python
# tests/security/conftest.py
import pytest


@pytest.fixture(scope="session")
def user_a(conf, api):
    """账号池：A、B 两个同角色用户，各自有独立数据。"""
    return login_as(conf, api, conf.accounts["user_a"])


@pytest.fixture(scope="session")
def user_b(conf, api):
    return login_as(conf, api, conf.accounts["user_b"])


@pytest.fixture(scope="session")
def order_b(user_b, base_url):
    """B 的订单，供 A 去越权访问。"""
    return user_b.post(f"{base_url}/api/orders", json={"sku_id": 1001, "num": 1}).json()["data"]
```

```python
# tests/security/test_permission.py
import pytest


# ── 水平越权：A 用自己的 token 访问 B 的资源 ──────────────
HORIZONTAL_CASES = [
    # (说明, 方法, 路径模板, 期望状态码)
    ("读取他人订单详情", "GET", "/api/orders/{order_no}", (403, 404)),
    ("取消他人订单",     "POST", "/api/orders/{order_no}/cancel", (403, 404)),
    ("读取他人收货地址", "GET", "/api/address/{address_id}", (403, 404)),
    ("修改他人备注",     "PATCH", "/api/orders/{order_no}", (403, 404)),
]

@pytest.mark.security
@pytest.mark.parametrize("desc, method, path_tpl, expected", HORIZONTAL_CASES,
                         ids=[c[0] for c in HORIZONTAL_CASES])
def test_horizontal(api_a, base_url, order_b, desc, method, path_tpl, expected):
    path = path_tpl.format(order_no=order_b["order_no"], address_id=order_b.get("address_id", 1))
    resp = api_a.request(method, f"{base_url}{path}")
    assert resp.status_code in expected, f"{desc} 越权成功: {resp.status_code} {resp.text[:300]}"


# ── 垂直越权：普通用户调管理员接口 ──────────────────────
VERTICAL_CASES = [
    ("禁用用户",     "POST", "/api/admin/users/disable"),
    ("查询全部订单", "GET",  "/api/admin/orders"),
    ("导出数据",     "POST", "/api/admin/export"),
    ("修改配置",     "PUT",  "/api/admin/config"),
]

@pytest.mark.security
@pytest.mark.parametrize("desc, method, path", VERTICAL_CASES, ids=[c[0] for c in VERTICAL_CASES])
def test_vertical(api_a, base_url, desc, method, path):
    resp = api_a.request(method, f"{base_url}{path}", json={"target": 1})
    assert resp.status_code == 403, f"{desc} 垂直越权成功: {resp.status_code} {resp.text[:300]}"
```

**四个让覆盖更彻底的做法：**

| 做法 | 说明 |
| --- | --- |
| **两个同角色账号** | 只有一个账号测不出水平越权 |
| **每个账号造独立数据** | B 的数据必须真实存在，否则 404 可能是"不存在"而不是"无权限"（**无法区分是缺陷还是数据问题**） |
| **覆盖所有入口** | path / query / body / 批量 / 导出，逐个参数化 |
| **打 `security` 标签** | `pytest -m security` 可以单独跑，放进夜间任务，不阻塞每次提交 |

**两个实操坑**：

1. **403 和 404 分不清**：如果 B 的数据不存在，返回 404 会让用例"通过"，但其实是数据没造出来。**所以 fixture 里必须先断言 B 的数据创建成功**。
2. **单点登录互踢**：A、B 账号如果共用同一账号池，登录会互相踢掉。**必须用两个独立账号，且不能并行跑同一账号**。

---

# 第三部分：AI 在接口测试中的用法

## 9. 三种用法（清单给的三条，说清各自的风险）

| 用法 | 能做什么 | 风险 |
| --- | --- | --- |
| 从 OpenAPI 生成初版用例 | 省掉"照文档抄参数"的机械工作 | 只覆盖成功路径；字段名可能编造 |
| 生成数据模型/断言模板（Pydantic/DTO） | 快速得到结构校验代码 | 可能把可选字段标成必填，反之亦然 |
| 审查用例是否只测成功路径 | 补漏视角 | AI 不知道你们的业务码分支和状态机 |

## 10. 自查 Q9 完整作答：审查 AI 生成用例的清单

**12 条，按"最可能出问题"排序：**

| # | 审查项 | 为什么 AI 会错 | 怎么改 |
| --- | --- | --- | --- |
| 1 | **只有成功路径** | AI 默认写"happy path" | 补参数非法、业务码分支、鉴权失败 |
| 2 | **只断言 200** | 训练语料里大量 `assert status == 200` | 改成五层断言（HTTP/业务码/字段/DB/副作用） |
| 3 | **字段名是编的** | AI 会"合理推测"字段名（`orderNo` vs `order_no`） | 以抓包/实际响应为准，逐个核对 |
| 4 | **业务码是编的** | 它不知道你们有 `40001/40002` | 从文档 responses 或代码枚举里取真实值 |
| 5 | **测试数据不可用** | 编一个 `sku_id=12345`，实际不存在 | 用 fixture 造，或从环境里查真实 ID |
| 6 | **没有清理步骤** | AI 不管残留数据 | 补前置清理 + 后置清理 |
| 7 | **参数边界是通用值** | 给"1 到 100"就写 50，不写 0/1/100/101 | 按边界值法补上点/内点/离点 |
| 8 | **没有幂等和并发** | 几乎不生成并发用例 | 补重复提交、并发修改、重试 |
| 9 | **没有权限用例** | 不知道你们有角色体系 | 补水平/垂直越权 |
| 10 | **环境/账号硬编码** | 直接写 `http://localhost:8080` | 抽到配置/fixture |
| 11 | **断言依赖文案** | `assert "成功" in resp.text` | 改成断言 code 和字段 |
| 12 | **用例之间依赖顺序** | 可能写成"先注册再登录再用同一个变量"的线性脚本 | 改成 fixture 隔离，能独立跑 |

### 10.1 一句话标准

> **AI 生成的是"骨架"，我补的是"四类血肉"：异常分支、业务断言、数据管理、权限。**
> 具体说：AI 写的用例我第一眼先看三件事 —— **只断了 200 吗？只有正向吗？字段名对不对？** 这三个问题几乎必中。

### 10.2 提示词要点（怎么让 AI 少犯错）

| 要点 | 原因 |
| --- | --- |
| 贴**真实响应**而不是只贴文档 | 响应里的字段名、错误码才是准的 |
| 明确说"要覆盖异常/边界/鉴权" | 不说它就只给正向 |
| 给出**团队断言的写法**（贴一段示例） | 它才会按你的五层断言模板写 |
| 明确要求"用 pytest + fixture + 参数化" | 否则给你 unittest 或串行脚本 |
| 让它**先列测试点再写代码** | 测试点可以人工审，代码不用逐行看 |

### 10.3 一条不可让渡的边界

> **测试数据和业务断言必须自己把关。** AI 不知道你们系统里哪个字段会影响后续流程（比如"库存为 0 时下单会走到审核分支"），也不知道哪些断言才是业务的真相。**它写得越顺，越要警惕"看起来对"。**

---

## 11. 动手清单

- [ ] 起一个 mock 第三方（Flask 20 行），让被测服务指向它，造一次超时和一次重复回调。
- [ ] 用 `GET /admin/calls` 验证被测服务在失败时到底重试了几次。
- [ ] 把"角色 × 接口"矩阵做成参数化，跑一次越权，看能查出几个 403 缺失。
- [ ] 让 AI 根据 Swagger 生成一版用例，用 §10 的 12 条清单逐条审，记录命中率。
