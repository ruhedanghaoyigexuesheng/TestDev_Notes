# 测试开发-Python语言核心篇

> 对应清单：语言核心【必须掌握】全部（Python 口径）
> 对应自查：Q1（写一个带超时和异常处理的取字段函数）
> 全篇约定：Python 3.10 + requests。文中代码都能直接跑，改掉 URL 就是你的工具函数。
> 立场：**测开写 Python 的评判标准不是"写得优雅"，而是"别人接手能看懂、失败时能查到原因、换环境能跑起来"。**

---

## 0. 先定位：测开的 Python 和开发的 Python 差在哪

| 开发关心 | 测开关心 |
| --- | --- |
| 功能正确、性能好 | **失败可定位**：报错能不能一眼看出是请求问题还是断言问题 |
| 抽象、可扩展 | **多环境可跑**：改配置不改代码 |
| 类型安全、设计模式 | **数据驱动**：加用例不加代码 |
| — | **脚本要能活过半年**：依赖锁死、别人能接手 |

所以本篇重点不是语法细节，而是这四件事怎么用 Python 做好。

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 异常处理 | 熟练 | 用错会造出"永远绿"的假用例 |
| requests 封装 | 熟练 | 每天都在用 |
| 集合选型 | 熟练 | 影响造数据速度和断言稳定性 |
| 文件读写 | 熟练 | JSON/YAML/CSV 是数据驱动的地基 |
| 类与对象 | 会用 | PO 模式、HTTP 客户端封装 |
| 依赖管理 | 会用 | CI 里环境不一致的根源 |
| 并发三模型 | 会用 | 并行跑用例 |
| 魔术方法 | 知道常用几个 | `__repr__` 调试最实用 |

---

## 1. 基本语法：真正天天用的只有这些

语法本身不用学，但**测试场景下的写法**有讲究。

### 1.1 异常处理：这是最容易写出假绿的地方

**反面教材，一定见过**：

```python
# ❌ 假绿：任何异常都被吞掉，用例永远通过
try:
    resp = requests.get(url, timeout=3)
    assert resp.json()["code"] == 0
except Exception:
    pass        # 请求超时、断言失败、字段不存在，全被吃掉
```

更隐蔽的版本：

```python
# ❌ 断言放在 try 里，AssertionError 继承了 Exception，被捕获后当"业务异常"处理
try:
    assert resp.json()["data"]["id"] == 1001
except Exception as e:
    logger.error("断言失败: %s", e)     # 只记日志，不 fail → 用例还是绿的
```

**正确姿势：断言不进 try。**

```python
def test_create_order(api):
    resp = api.post("/api/order", json={"sku_id": 1, "num": 1})
    # 断言都放在最外层，失败就是失败
    assert resp.status_code == 200, resp.text          # 把响应体带上，失败时才知道为什么
    body = resp.json()
    assert body["code"] == 0, body
    assert body["data"]["order_id"]
```

**需要 try 的只有"预期的异常"**，而且要抓得准、抛得清：

```python
import logging
import requests

logger = logging.getLogger(__name__)

def get_user(uid: int) -> dict:
    url = f"{BASE}/api/users/{uid}"
    try:
        resp = requests.get(url, timeout=(3, 10))
    except requests.Timeout:
        # 超时是可重试的，记日志后往上抛，别自己吞
        logger.warning("请求超时 url=%s timeout=(3,10)", url)
        raise
    except requests.ConnectionError as e:
        # 连接错误通常是环境问题，包装成更明确的错误，保留原始异常链
        raise RuntimeError(f"连不上测试环境，检查 VPN/hosts：{url}") from e

    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {resp.status_code} {resp.text[:500]}")
    return resp.json()
```

几条硬规则，写在团队规范里：

| 规则 | 原因 |
| --- | --- |
| 禁止 `except:` 和 `except Exception: pass` | 造出假绿，最不可救的 bug |
| 断言不写在 try 块里 | `AssertionError` 是 `Exception` 子类，会被误捕 |
| 捕获后要么 `raise`，要么 `raise Xxx from e` | 保留原始堆栈，否则排查时全是"我包装的那句话" |
| 只捕获你能处理的异常 | 乱捕会让真正的 bug 隐蔽 |
| 用 `pytest.raises` 断言"应该抛异常" | 别手写 try/except 判断 |

```python
# 测"非法参数应报错"，用 pytest.raises 而不是 try/except
import pytest

def test_invalid_sku(api):
    with pytest.raises(requests.HTTPError) as exc:
        api.post("/api/order", json={"sku_id": -1}).raise_for_status()
    assert exc.value.response.status_code == 400
```

### 1.2 其他天天用的写法

```python
# f-string：拼 URL、拼断言信息，比 % 和 format 都清楚
url = f"{base}/api/users/{uid}?page={page}"

# 推导式：造数据、过滤集合，最常用
ids = [u["id"] for u in users if u["status"] == "active"]
byname = {u["name"]: u for u in users}          # 转 dict 便于查找

# 解包：函数返回多值
status, body = fetch(...)

# 海象运算符：少一行临时变量（别滥用，可读性优先）
if (token := resp.headers.get("X-Token")):
    session.headers["Authorization"] = token

# for-else：找遍了都没找到才执行 else，适合"断言不存在某个元素"
for item in items:
    if item["name"] == "admin":
        break
else:
    pytest.fail("菜单里没有 admin")
```

---

## 2. 面向对象：测试里只有三个正当用途

清单说"能设计简单封装即可"，所以别纠结设计模式。**测开写类，只有三个场景是值得的：**

1. **封装一个被测系统的客户端**（`ApiClient`），统一处理 base_url、鉴权、超时、日志。
2. **封装页面/模块对象**（Page Object），把"怎么点"和"测什么"分开。
3. **封装测试数据对象**（`Order`、`User`），用 dataclass，让造数据能带默认值。

超过这三个场景的类，多半是在给自己挖坑。三层继承的测试框架，接手的人一定骂。

### 2.1 四个必须懂的魔术方法

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiResponse:
    """包装一次请求的结果。dataclass 自动生成 __init__/__repr__/__eq__，
    失败时 print 出来直接可读，不用自己写 __repr__。"""
    status: int
    body: Any
    elapsed: float
    url: str = ""
    headers: dict = field(default_factory=dict)   # 可变默认值必须用 field(default_factory=...)！

    @property
    def code(self) -> Any:
        """业务码，统一取法。"""
        return self.body.get("code") if isinstance(self.body, dict) else None

    def __bool__(self) -> bool:
        """让 `if resp:` 表示"HTTP 成功且业务成功"。⚠️ 自定义 __bool__ 要谨慎，
        容易让人误以为对象存在与否，团队里要么统一用、要么不用。"""
        return self.status == 200 and self.code == 0
```

| 魔术方法 | 用途 | 测开里为什么用 |
| --- | --- | --- |
| `__repr__` | 打印对象 | **调试第一需求**。默认的 `<object at 0x7f...>` 等于没信息 |
| `__eq__` | 对象比较 | 断言"期望的数据对象 == 实际的数据对象"，比逐字段断言清楚 |
| `__enter__` / `__exit__` | `with` 上下文 | 资源清理（临时文件、DB 连接、mock 开关），**保证异常时也清理** |
| `__call__` | 让实例可调用 | 写 fixture 工厂：`user_factory(role="admin")` |

### 2.2 可变默认参数：这个坑 100% 会遇到

```python
# ❌ 默认值只在函数定义时创建一次，所有调用共享同一个 list
def add_step(name, steps=[]):
    steps.append(name)
    return steps

add_step("a")   # ['a']
add_step("b")   # ['a', 'b']  ← 不是 ['b']

# ✅ 用 None 做默认值
def add_step(name, steps=None):
    steps = steps or []
    steps.append(name)
    return steps
```

同一个坑的类版本（更隐蔽）：

```python
class CaseCollector:
    cases = []          # ❌ 类属性，所有实例共享

    def add(self, c):
        self.cases.append(c)

class CaseCollector:
    def __init__(self):
        self.cases = []  # ✅ 实例属性
```

**测试里的实际表现**：用例 A 的结果出现在用例 B 的报告里；参数化用例之间互相污染。看到"用例单独跑通过、一起跑失败"，先查这种共享可变状态。

### 2.3 组合优于继承：一个真实的封装

```python
import logging
import time
import requests

logger = logging.getLogger(__name__)


class ApiClient:
    """统一封装：base_url、鉴权、超时、日志、耗时。

    设计要点（面试可以讲）：
    1. 组合 requests.Session 而不是继承 Session —— 我们只要它的连接复用，不要它的全部接口
    2. 所有请求走同一个入口 _request，日志和耗时只写一份
    3. 不要在封装里做断言 —— 断言属于用例，客户端只负责"发出去、拿回来"
    """
    def __init__(self, base_url: str, token: str | None = None,
                 timeout: tuple[float, float] = (3, 10)):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        start = time.perf_counter()
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.Timeout:
            logger.warning("TIMEOUT %s %s timeout=%s", method, url, self.timeout)
            raise
        except requests.ConnectionError:
            logger.error("CONN_ERROR %s %s", method, url)
            raise
        cost = time.perf_counter() - start
        logger.info("%s %s -> %s (%.3fs)", method, url, resp.status_code, cost)
        return resp

    def get(self, path: str, **kw):
        return self._request("GET", path, **kw)

    def post(self, path: str, **kw):
        return self._request("POST", path, **kw)

    def close(self):
        self.session.close()
```

这段代码的价值：**以后所有接口用例都从 `ApiClient` 出发，日志、超时、鉴权只维护一处。** 这就是"能设计简单封装"的标准答案。

---

## 3. 集合选型：选错会让造数据脚本慢 100 倍

### 3.1 选型表

| 类型 | 有序 | 可变 | 元素可重复 | 查找 | 测开里典型用途 |
| --- | --- | --- | --- | --- | --- |
| `list` | 是 | 是 | 是 | O(n) | 用例列表、参数列表、响应数组 |
| `tuple` | 是 | **否** | 是 | O(n) | 固定配置、函数多返回值、dict 的 key |
| `dict` | 是（3.7+） | 是 | key 唯一 | O(1) | JSON 对象、配置、按 id 索引 |
| `set` | **否** | 是 | 否 | O(1) | 去重、集合运算、快速判断存在 |

**一句话记法**：需要顺序和下标用 list；需要"按 key 查"用 dict；需要"存在性判断/去重"用 set；需要不可变（能当 key、防误改）用 tuple。

### 3.2 四个真实场景

```python
# ① 去重且保持顺序：dict.fromkeys（set 会打乱顺序）
uniq = list(dict.fromkeys(skus))          # ['a','b','c']
# 用 set 的后果：顺序没了，断言顺序时会失败

# ② 存在性判断：一定要用 set，别用 list
#   sku_id in sku_set    → O(1)
#   sku_id in sku_list   → O(n)，放在循环里就是 O(n²)

# ③ 集合运算：比对两个环境的差异
only_prod = set(prod_skus) - set(test_skus)
only_test = set(test_skus) - set(prod_skus)
both = set(prod_skus) & set(test_skus)

# ④ 参数组合：用 itertools.product 生成笛卡尔积，别手写嵌套循环
from itertools import product
cases = list(product(["alipay", "wechat"], ["1", "0"], ["v1", "v2"]))   # 8 组
```

### 3.3 断言里的坑：set 无序

```python
# ❌ 顺序不稳定，偶发失败
assert list(set(resp["tags"])) == ["a", "b", "c"]

# ✅ 要么排序，要么比较集合
assert sorted(set(resp["tags"])) == ["a", "b", "c"]
assert set(resp["tags"]) == {"a", "b", "c"}
```

这个坑会在"Python 3.7 前 dict 无序"的老项目里更明显，但现在也常见于把 set 直接 `json.dumps` 落盘后再比对的写法。

---

## 4. 文件读写：数据驱动的地基

### 4.1 编码：Windows 上最容易踩的坑

```python
# ❌ 不写 encoding → 用系统默认编码（中文 Windows 是 GBK）→ 读 UTF-8 文件报 UnicodeDecodeError
with open("data.yaml") as f:
    ...

# ✅ 永远显式写 encoding
with open("data.yaml", encoding="utf-8") as f:
    ...

# 读 CSV 更要注意：Excel 导出的中文 CSV 常是 GBK
with open("cases.csv", encoding="gbk", newline="") as f:
    ...
```

`newline=""` 是 CSV 的标准写法，不写会在 Windows 上多出空行。

### 4.2 路径：用 pathlib，别拼字符串

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # 当前文件所在目录
DATA = ROOT / "data" / "cases.yaml"             # / 拼接，跨平台
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)          # 不存在就建，包括父目录

if not DATA.exists():
    raise FileNotFoundError(f"数据文件不存在: {DATA}")   # 报错带上绝对路径

# 遍历目录下所有 json
for p in (ROOT / "cases").rglob("*.json"):
    ...
```

**为什么重要**：CI 里工作目录和执行目录经常不是同一个，用 `os.getcwd()` 拼相对路径一定出事。`Path(__file__)` 是唯一可靠的基准。

### 4.3 JSON

```python
import json

# 读
with open(p, encoding="utf-8") as f:
    data = json.load(f)

# 写：ensure_ascii=False 保留中文可读，indent 便于 diff 和 code review
with open(p, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

**必须养成的习惯：失败时把响应体落盘。** 光看日志里的 `resp.text[:200]` 往往不够（排查问题经常需要完整报文）：

```python
import json
from pathlib import Path


def dump_failure(resp, name: str, out_dir: Path):
    """用例失败时把现场存成文件，便于事后分析/贴到缺陷单。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "request": {
            "method": resp.request.method,
            "url": resp.request.url,
            "headers": dict(resp.request.headers),
            "body": resp.request.body if isinstance(resp.request.body, str)
                    else (resp.request.body or b"").decode("utf-8", "replace"),
        },
        "response": {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text,
        },
        "elapsed_seconds": resp.elapsed.total_seconds(),
    }
    path = out_dir / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
```

### 4.4 CSV（参数化数据最常用的格式）

```python
import csv

def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))       # 第一行自动当表头，每行一个 dict

# 用法：写一个 cases/cart_add.csv
# case_name,sku_id,num,expected_code
# 正常加购,1001,1,0
# 数量为0,1001,0,400
```

坑：

- `DictReader` 读出来的值**全是字符串**，判断 `int` 时要转换。
- Excel 存 CSV 可能带 BOM（`\ufeff`），导致第一列表头变成 `\ufeffcase_name`。用 `encoding="utf-8-sig"` 解决，这一条非常值得记住。
- 数字前导 0 被 Excel 吃掉（手机号变 1380000000），测试数据要加引号或用文本格式。

### 4.5 YAML（配置文件常态）

```python
import yaml

def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        # 必须用 safe_load，load 能执行任意 Python 对象，等于代码注入
        return yaml.safe_load(f) or {}
```

YAML 三个坑：

| 坑 | 例子 | 处理 |
| --- | --- | --- |
| `yes/no/on/off` 被解析成布尔 | `enabled: no` → `False` | 配置值加引号，或统一用 `true/false` |
| 版本号被当数字 | `version: 1.10` → `1.1` | 加引号 `"1.10"` |
| 日期被转成 date 对象 | `date: 2026-10-28` → `datetime.date` | 加引号，或 json 序列化时 `default=str` |

这些坑在"配置里放版本号/开关"时百分百遇到，面试也能讲。

---

## 5. 模块与依赖管理

### 5.1 最小可复现流程

```bash
# 创建并激活虚拟环境（每个项目一个，别用全局 python）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 5.2 requirements：锁版本是纪律，不是建议

```
# requirements.txt —— 测试工程的最小示范
requests==2.31.0
pytest==7.4.0
pytest-xdist==3.5.0
pytest-rerunfailures==12.0
pytest-timeout==2.2.0
PyYAML==6.0.1
```

三条规则：

1. **锁精确版本（`==`）**，不要 `>=`。CI 某天突然挂了，十有八九是某个依赖自己升级了。
2. **区分运行时与开发依赖**：`requirements.txt` + `requirements-dev.txt`（lint、报告等），减少 CI 安装量。
3. **别用 `pip freeze` 生成项目依赖**。它会把环境里所有包（包括你 `pip install` 试玩留下的）全写进去，导致依赖膨胀、传递依赖被锁死。正确做法是手工维护直接依赖，或用 `pip-tools`：

```bash
pip install pip-tools
# requirements.in 里只写直接依赖，不带版本或带宽松版本
pip-compile --output-file=requirements.txt requirements.in   # 生成锁文件（含全部传递依赖）
pip-sync requirements.txt
```

### 5.3 pyproject.toml（新项目推荐）

```toml
[project]
name = "qa-autotest"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "requests==2.31.0",
    "PyYAML==6.0.1",
]

[project.optional-dependencies]
dev = ["pytest==7.4.0", "pytest-xdist==3.5.0", "ruff==0.6.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

`[tool.pytest.ini_options]` 写在 `pyproject.toml` 里，就不用再维护 `pytest.ini`，配置**和依赖放在一处**，新人 clone 下来一次搞定。

### 5.4 国内镜像

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

CI 里如果没有镜像，装一个 pytest 生态的包可能要等几分钟，**这是流水线慢的常见原因，比优化代码收益大**。

---

## 6. requests：把细节用对

### 6.1 三个参数的区别（新手最常混）

| 参数 | 作用 | 实际发出的 |
| --- | --- | --- |
| `params={"page": 1}` | 拼到 URL 查询串 | `?page=1` |
| `data={"a": 1}` | **表单**编码 | `Content-Type: application/x-www-form-urlencoded`，body `a=1` |
| `json={"a": 1}` | **JSON** 编码 | `Content-Type: application/json`，body `{"a": 1}` |

**最常见的错误**：服务端要 JSON，脚本写了 `data={"a":1}`，接口返回 400 或字段全 null。**排查方法：`print(resp.request.headers)`**，一眼就能看出 `Content-Type` 是 form 还是 json。

### 6.2 超时：必须同时给连接和读取

```python
# ❌ 不设超时：请求可能永远挂着，CI 卡死，排查时以为是死锁
requests.get(url)

# ⚠️ 单值超时：连接和读取都用 10s，但语义模糊
requests.get(url, timeout=10)

# ✅ 元组：(连接超时, 读取超时)
requests.get(url, timeout=(3, 10))
```

区分两种超时的实际价值：

- **连接超时**（3s）：TCP 建连阶段。报这个说明网络/端口/防火墙有问题，重试通常没用。
- **读取超时**（10s）：连上了但服务端迟迟不响应。报这个说明后端慢，重试可能有用（但要考虑幂等）。

排查时看到 `ConnectTimeout` 和 `ReadTimeout`，**结论完全不同**，所以超时必须设成元组，别用一个数字糊过去。

### 6.3 Session：复用连接 + 保持登录态

```python
import requests

s = requests.Session()
s.headers.update({"User-Agent": "qa-autotest/1.0"})
s.post(f"{BASE}/api/login", json={"user": "qa", "pwd": "p"})   # 自动存 cookie

r = s.get(f"{BASE}/api/orders")     # 自动带 cookie，且复用 TCP 连接
```

用 Session 的三个理由：

1. **连接复用**：省调握手开销，压测和批量用例下差别巨大（网络篇讲过 TIME_WAIT）。
2. **自动管理 Cookie**。
3. **统一默认 Header**。

注意：`requests.Session` **不是线程安全的**。多线程并发时每线程一个 Session，或加锁（网络篇给过 `threading.local` 的写法）。

### 6.4 异常类型要分清

| 异常 | 什么时候抛 | 排查方向 |
| --- | --- | --- |
| `requests.exceptions.MissingSchema` | URL 没写 `http://` | 配置错误 |
| `ConnectionError` | DNS 失败、端口不通、被拒 | 环境、VPN、hosts、服务未启动 |
| `ConnectTimeout` | 建连超时 | 网络、防火墙 |
| `ReadTimeout` | 连上了但读取超时 | 后端慢、DB 慢、死锁 |
| `TooManyRedirects` | 重定向循环 | Cookie/登录态失效被反复重定向到登录页 |
| `HTTPError`（由 `raise_for_status()` 主动抛） | 4xx/5xx | 接口行为问题 |

`raise_for_status()` 只在你想把 4xx/5xx 当异常时才调；**接口测试里往往不该调**，因为你要断言具体的错误码。

### 6.5 中文乱码：`resp.encoding`

```python
# 服务端返回 Content-Type: application/json 时正常
# 返回 text/html 且没写 charset 时，requests 默认按 ISO-8859-1 解码 → 中文乱码
resp.encoding = resp.apparent_encoding      # 或者直接指定
resp.encoding = "utf-8"
print(resp.text)
```

断言中文报错信息时踩过这个坑，就会记得：**先看 `resp.encoding`，再看 `resp.text`。**

---

## 7. 并发：线程 / 进程 / 协程怎么选

### 7.1 一句话选型

| 模型 | 适合 | 测试场景 | 代价 |
| --- | --- | --- | --- |
| 线程 `ThreadPoolExecutor` | IO 密集 | **并行跑接口用例**（等网络的时间占 95%） | GIL 限制 CPU 并行；共享状态要小心 |
| 进程 `ProcessPoolExecutor` | CPU 密集 | 图片比对、大报文签名、压测造数据 | 创建慢（Windows 是 spawn）、进程间不能共享对象 |
| 协程 `asyncio` | 高并发 IO | 压测脚本、批量探测 | 全链路异步，库要支持（`aiohttp`/`httpx`），不能混用同步库 |

**结论直接背**：接口用例用线程池；CPU 计算用进程池；要做万级并发压测用协程。

### 7.2 线程池跑用例（最常用的形态）

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logger = logging.getLogger(__name__)

def run_cases(cases: list[dict], fn, max_workers: int = 10) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(fn, c): c for c in cases}
        for fut in as_completed(future_map):
            case = future_map[fut]
            try:
                results.append(fut.result())          # 异常在这里抛出
            except Exception as e:
                # 关键：线程里的异常不会自动冒泡到主线程，必须显式收集
                logger.error("用例失败 case=%s err=%s", case.get("case_name"), e, exc_info=True)
                results.append({"case": case, "error": repr(e)})
    return results
```

**坑 1：线程里的异常会被静默吞掉**。用 `future.result()` 取结果才会抛出来，否则你只能看到"跑完了但没结果"。

**坑 2：不要在线程里共享 Session / driver / 全局可变状态**（见第 2.2 节）。

### 7.3 协程（了解形态即可）

```python
import asyncio
import aiohttp

async def one(session, url, sem):
    async with sem:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return resp.status

async def main(urls):
    sem = asyncio.Semaphore(50)
    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(*[one(session, u, sem) for u in urls])

# asyncio.run(main(urls))
```

协程的价值在"一个线程扛几千并发"，测普通接口用线程池足够，别为了炫技引入 async 复杂度。

---

## 8. 自查 Q1 完整作答：带超时和异常处理的取字段函数

题目要求：请求指定 URL，返回状态码和响应 JSON 中指定字段的值，带超时和异常处理。

### 8.1 基础版（面试先写这个）

```python
import requests


def fetch_field(url: str, field: str, timeout: float = 10) -> tuple[int, object]:
    """请求 URL，返回 (状态码, 字段值)。

    设计取舍：
    - 非 2xx 不抛异常，因为测试需要看到状态码和错误响应
    - 响应不是 JSON 时抛 ValueError，并带上状态码和原文片段
    - 字段不存在返回 None（用 dict.get 的语义），而不是抛 KeyError
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url 必须以 http(s):// 开头: {url}")

    try:
        resp = requests.get(url, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"请求超时({timeout}s): {url}") from None
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"连接失败: {url}") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"请求异常: {e}") from e

    try:
        body = resp.json()
    except ValueError:
        raise ValueError(f"响应不是 JSON (status={resp.status_code}): {resp.text[:200]}")

    if not isinstance(body, dict):
        raise ValueError(f"响应 JSON 不是对象，无法取字段: {type(body).__name__}")

    return resp.status_code, body.get(field)
```

### 8.2 工程版（加日志、嵌套字段、连接复用）

面试时说完基础版，主动说"实际项目里我会再考虑四点"，然后给这版：

```python
import logging
import requests

logger = logging.getLogger(__name__)


def _dig(data: object, path: str) -> object:
    """支持 'a.b.c' 和 'items[0].id' 这种路径。找不到返回 None。"""
    if not path:
        return data
    cur = data
    for part in path.split("."):
        name, _, idx = part.partition("[")
        if name:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(name)
            if cur is None:
                return None
        if idx:
            try:
                i = int(idx.rstrip("]"))
                cur = cur[i]
            except (ValueError, IndexError, TypeError):
                return None
    return cur


def fetch_field(url: str,
                field: str = "",
                timeout: tuple[float, float] = (3, 10),
                headers: dict | None = None,
                session: requests.Session | None = None) -> tuple[int, object]:
    """请求 URL，返回 (状态码, JSON 中字段值)。

    - timeout 用元组区分 (连接超时, 读取超时)
    - field 支持点路径和下标：'data.order.id'、'items[0].sku'
    - session 可传入复用连接；不传则新建（用完即关）
    """
    own_session = session is None
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=timeout, headers=headers or {})
    except requests.exceptions.ConnectTimeout:
        logger.error("连接超时 url=%s connect_timeout=%s", url, timeout[0])
        raise
    except requests.exceptions.ReadTimeout:
        logger.error("读取超时 url=%s read_timeout=%s", url, timeout[1])
        raise
    except requests.exceptions.ConnectionError:
        logger.error("连接失败 url=%s（检查服务是否启动、hosts、VPN）", url)
        raise
    finally:
        if own_session:
            sess.close()

    logger.info("GET %s -> %s (%.3fs)", url, resp.status_code, resp.elapsed.total_seconds())

    try:
        body = resp.json()
    except ValueError:
        logger.error("非 JSON 响应 status=%s body=%s", resp.status_code, resp.text[:300])
        raise ValueError(f"响应不是 JSON (status={resp.status_code})") from None

    return resp.status_code, _dig(body, field)
```

### 8.3 面试官大概率追问的五个点（提前准备）

| 追问 | 怎么答 |
| --- | --- |
| 响应不是 JSON 怎么办 | 显式抛 `ValueError` 并带上状态码和原文片段；或者设计成返回 `(status, None, raw)` 三元组，让调用方决定 |
| 字段不存在返回 None 还是抛异常 | 取决于用法：做"存在性断言"返回 None 更好用；做"必填校验"应该抛，否则 `assert None == 1001` 的失败信息不直观。**团队里要统一，我的偏好是补一个 `required=True` 参数** |
| 4xx/5xx 要不要抛 | **不抛**。测试需要拿到状态码做断言，抛了就丢了信息。调用方需要时自己 `raise_for_status()` |
| 超时怎么设 | 元组 (connect, read)，connect 小（3s，网络问题重试无用），read 按接口 P99 估（10s），**不能拍脑袋，要看监控的 P99** |
| 要不要加日志 | 必须。而且日志里要有 URL、状态码、耗时；断言失败时能直接看出是大是小 |

### 8.4 顺手补一个单测（这是工本篇的伏笔）

```python
from unittest.mock import patch
import pytest


def test_fetch_field_nested():
    class FakeResp:
        status_code = 200
        elapsed = type("E", (), {"total_seconds": lambda self: 0.1})()
        text = '{"data":{"items":[{"sku":"A1"}]}}'

        def json(self):
            return {"data": {"items": [{"sku": "A1"}]}}

        def __init__(self):
            self.request = None
            self.headers = {}

    with patch("requests.Session.get", return_value=FakeResp()):
        status, value = fetch_field("http://x.test/api", "data.items[0].sku")
    assert status == 200
    assert value == "A1"


def test_fetch_field_timeout():
    import requests
    with patch("requests.Session.get", side_effect=requests.exceptions.ConnectTimeout()):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            fetch_field("http://x.test/api", "a")
```

**注意**：`requests.Session.get` 的 patch 路径要打在"使用处"（这里就是 `requests.Session.get`”，因为我们的代码用的是 `sess.get`）。patch 路径写错是 mock 最常见的失败原因，pytest 篇会细讲。

---

## 9. 复习动作清单

- [ ] 把 §8.2 的 `fetch_field` 放进你的工具库，用它替换掉自己脚本里 `requests.get(...)` + `resp.json()["x"]` 的裸写。
- [ ] 翻一遍现有脚本，搜 `except` 和 `pass`，找出至少一处"吞异常"的地方改掉。
- [ ] 把一个硬编码的测试环境地址，改成从 YAML 配置读（配置篇会讲完整方案，先动手）。
- [ ] 用 `ThreadPoolExecutor` 把一段 `for` 循环跑 100 个接口请求改成并行，记录耗时差异。
- [ ] 给一个有中文报错信息的接口写断言，故意用 `resp.text` 看是否乱码，练 `resp.encoding` 的处理。
