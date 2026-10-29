# 测试开发-MySQL篇

> 对应清单：MySQL【必须掌握】全部 +【了解即可】全部
> 对应自查：Q1（两表 JOIN 查最近 7 天待支付订单）、Q2（隔离级别 + 重复提交与什么机制有关）
> 立场：测开写 SQL 只有三个目的 —— **造数据、校验数据、排查数据**。不是拿它当开发用，是拿它当"真相来源"。

---

## 0. 先定位：SQL 在测开工作里出现在哪

| 场景 | 用什么 | 为什么必须会 |
| --- | --- | --- |
| 造测试数据 | INSERT / UPDATE / 批量造数 | 接口造数据慢且受业务规则限制，直接写库最快 |
| 校验接口正确性 | SELECT 查表比对 | 接口返回 200 不代表数据对，**库里的状态才是真相** |
| 排查"接口查不到" | SELECT + 主从/缓存分析 | 判断是没落库、落错库、还是被缓存挡住了 |
| 定位性能问题 | EXPLAIN / 慢查询日志 | 接口慢时先看是不是 SQL 慢 |
| 清理脏数据 | DELETE / UPDATE 带条件 | 测试环境数据污染是常态 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| SELECT 过滤/排序/分页/聚合/JOIN | 熟练 | 每天写 |
| 索引与唯一约束在测试中的意义 | 熟练 | 幂等、防重的最后防线 |
| 事务与隔离级别 | 会用能讲清 | 并发用例必踩 |
| 用 SQL 做数据断言 | 熟练 | 本篇核心 |
| EXPLAIN / 慢 SQL / 索引失效 | 看得懂 | 和性能测试衔接 |
| 连接数耗尽 | 知道现象 | 报错长什么样 |

---

## 1. 常见 SQL：会写，还要知道哪里会坑测试

### 1.1 查询、过滤、排序、分页

```sql
-- 基础：最近 7 天、待支付、按创建时间倒序
SELECT order_no, user_id, status, amount, created_at
FROM orders
WHERE status = 'PENDING_PAY'
  AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY created_at DESC
LIMIT 20;
```

**分页两个坑，测开一定会遇到：**

```sql
-- 坑 1：深分页。LIMIT 100000, 20 会先扫描 100020 行再丢前 100000 行 → 越翻越慢
SELECT * FROM orders ORDER BY id LIMIT 100000, 20;

-- 正确做法：记住上一页最后一条的 id（游标分页）
SELECT * FROM orders WHERE id > 100000 ORDER BY id LIMIT 20;
```

测试时的表现：接口翻到第 500 页超时。**这不是接口 bug，是分页写法问题**，但你要能指出来。

```sql
-- 坑 2：排序字段不唯一 → 分页出现重复或漏数据
ORDER BY created_at DESC               -- 同一秒创建的几十条订单，顺序不稳定
ORDER BY created_at DESC, id DESC      -- ✅ 加唯一列兜底
```

**测试怎么发现这个问题**：连续翻页收集所有 id，看有没有重复或缺失。数据量大时必现。

**时间条件的两种写法，语义不同**（面试常问）：

```sql
-- 最近 7 天（滚动 168 小时）
created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)

-- 最近 7 个自然日（含今天往前数 7 天，从 0 点算）
created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
```

差别在跨天的那一刻。**测试对账时如果两边写法不一致，会差一整天的数据** —— 这种 bug 只有对账才发现。

### 1.2 聚合：GROUP BY / HAVING

```sql
-- 每个用户的待支付订单数和总金额，只显示金额超过 100 的
SELECT u.nickname,
       COUNT(*)            AS order_cnt,
       SUM(o.amount)       AS total_amount
FROM orders o
INNER JOIN users u ON u.id = o.user_id
WHERE o.status = 'PENDING_PAY'
GROUP BY u.id, u.nickname
HAVING SUM(o.amount) > 100
ORDER BY total_amount DESC;
```

三个必须分清的点：

| 区别 | 说明 | 测试意义 |
| --- | --- | --- |
| `WHERE` vs `HAVING` | WHERE 过滤**行**（聚合前），HAVING 过滤**组**（聚合后） | 用错会得到完全不同结果，且不报错 |
| `COUNT(*)` vs `COUNT(col)` | 后者不统计 NULL | 统计"有备注的订单数"时结果差很多 |
| `SUM` 遇 NULL | 返回 NULL，不是 0 | 断言 `SUM(amount) == 0` 会失败，要用 `IFNULL(SUM(amount), 0)` |

**测开常用聚合场景**：

```sql
-- 对账：接口返回的总金额 vs 库里算出来的总金额
SELECT COUNT(*) AS cnt, IFNULL(SUM(amount),0) AS total
FROM orders
WHERE user_id = 1001 AND status = 'PAID'
  AND created_at >= '2026-10-01' AND created_at < '2026-11-01';
```

### 1.3 关联查询 JOIN

```sql
-- INNER JOIN：只返回两边都匹配的
SELECT o.order_no, u.nickname
FROM orders o INNER JOIN users u ON u.id = o.user_id;

-- LEFT JOIN：保留左表全部，右表没匹配到就补 NULL
SELECT u.id, u.nickname, o.order_no
FROM users u LEFT JOIN orders o ON o.user_id = u.id;
```

**LEFT JOIN 在测试里最重要的用途：找"孤儿数据"。**

```sql
-- 有订单但找不到用户（数据不一致，通常是外键被禁用或脏数据）
SELECT o.id, o.order_no, o.user_id
FROM orders o
LEFT JOIN users u ON u.id = o.user_id
WHERE u.id IS NULL;

-- 用户一个订单都没有（验证"注册后应自动发新人券"这类场景之前，先确认没数据）
SELECT u.id, u.nickname
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.id IS NULL;
```

这段 SQL 是**线上数据体检**的标配。测试环境跑一遍，常能发现造数据脚本留下的孤儿记录，导致某些查询报错或返回异常。

JOIN 的三个坑：

| 坑 | 后果 | 怎么发现 |
| --- | --- | --- |
| 一对多 JOIN 导致行数膨胀 | `COUNT` 变大、`SUM` 翻倍 | 先 `COUNT(*)` 对比主表行数 |
| `ON` 条件写漏（笛卡尔积） | 结果爆炸 | 忘记写 ON 时行数 = 两表乘积 |
| 用 `WHERE` 过滤右表，把 LEFT JOIN 变成了 INNER JOIN | 左表没匹配的行也消失了 | 把条件移到 `ON` 里 |

```sql
-- ❌ 这样写，LEFT JOIN 退化成 INNER JOIN（没订单的用户被过滤掉了）
SELECT u.id, o.order_no
FROM users u LEFT JOIN orders o ON o.user_id = u.id
WHERE o.status = 'PAID';

-- ✅ 条件放 ON 里
SELECT u.id, o.order_no
FROM users u LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'PAID';
```

**这是 SQL 里最容易错、也最容易被面试官追问的一个点。**

---

## 2. 表结构：主键、唯一索引、普通索引、外键

### 2.1 四种约束的角色

```sql
CREATE TABLE orders (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,     -- 主键：唯一 + 聚簇索引
  order_no   VARCHAR(32) NOT NULL,
  user_id    BIGINT NOT NULL,
  status     VARCHAR(16) NOT NULL,
  amount     DECIMAL(10,2) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_order_no (order_no),                -- 唯一索引：业务唯一性
  KEY idx_user_created (user_id, created_at),       -- 普通索引：加速查询
  CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;
```

| 类型 | 约束 | 性能 | 测试关注点 |
| --- | --- | --- | --- |
| 主键 | 唯一 + 非空 | 聚簇索引，查询最快 | 自增主键是否被用满（INT 溢出）、主键乱序导致页分裂 |
| 唯一索引 | 唯一 + 允许多个 NULL | 写入时多一次校验 | **幂等的最后一道防线**：重复提交能不能被拦 |
| 普通索引 | 无约束 | 加速 WHERE/ORDER BY | 有没有、走没走（EXPLAIN） |
| 外键 | 引用完整性 | **有性能开销**，高并发下易锁 | 阿里规范禁止物理外键，测试要验证**应用层有没有做关联校验** |

### 2.2 唯一索引 = 幂等的地基（这是测试最该关心的）

```
用户连点两次提交 → 两个请求同时到达
应用层"先查有没有，再插入" → 两个请求都查到"没有" → 都插入 → 两条订单
```

**应用层的"先查后插"在并发下必然失效**（查和插之间有窗口）。真正兜底的是唯一索引：

```sql
INSERT INTO orders (order_no, user_id, status, amount)
VALUES ('O-20261029-001', 1001, 'PENDING_PAY', 99.00);
-- 第二个请求：ERROR 1062 (23000): Duplicate entry 'O-20261029-001' for key 'uk_order_no'
```

**测试动作**：用 10 并发提交同一个 `request_id`/`order_no`，断言只有 1 条记录、且接口对重复请求返回"幂等成功"（返回第一次的订单）而不是 500。

如果返回 500（`Duplicate entry`），说明开发只在应用层查重、没捕获唯一索引冲突 → **这是要提的缺陷**，因为并发场景下用户会看到报错。

### 2.3 外键：为什么生产通常不用

| 外键的好处 | 外键的代价 |
| --- | --- |
| 数据库层保证引用完整性 | 每次写入都要检查父表，有额外锁 |
| 级联删除方便 | 分库分表后根本用不了 |
| | 高并发下容易死锁、锁等待 |

**测试必须知道的影响**：如果数据库不建外键，那"订单的 user_id 指向不存在的用户"这种脏数据**数据库不会拦**，只能靠应用层。所以：

- 测"删除用户后，其订单怎么处理" → 要验证应用层是逻辑删除还是级联，别指望数据库。
- 跑数据体检 SQL（§1.3 的孤儿数据检测）→ 这是发现这类问题的唯一手段。

### 2.4 索引三问

```
有没有？   → SHOW INDEX FROM orders;
走没走？   → EXPLAIN，看 key 列是不是 NULL
够不够？   → 看 rows 扫描行数、Extra 有没有 filesort/temporary
```

---

## 3. 事务：ACID、隔离级别、三种读问题

### 3.1 ACID 各对应一个测试现象

| 特性 | 含义 | 测试里怎么体现 |
| --- | --- | --- |
| 原子性 A | 要么全成功要么全回滚 | 下单扣库存+建订单，中间失败时**两个都不能生效** |
| 一致性 C | 约束在事务前后都成立 | 转账前后总金额不变（余额不能出现负数） |
| 隔离性 I | 并发事务互不干扰 | 两个用户并发抢最后一件库存，只有一个成功 |
| 持久性 D | 提交后不丢 | 提交后 kill 数据库进程，重启数据还在 |

**最实用的测试点是原子性**：故意让事务第二步失败（比如传入非法值），验证第一步的写入是否被回滚。这是"接口返回失败但数据部分写入"类 bug 的根源。

### 3.2 四种隔离级别

| 隔离级别 | 脏读 | 不可重复读 | 幻读 | MySQL 默认 |
| --- | --- | --- | --- | --- |
| READ UNCOMMITTED（读未提交） | 会 | 会 | 会 | |
| READ COMMITTED（读已提交） | 不会 | 会 | 会 | Oracle 默认 |
| **REPEATABLE READ（可重复读）** | 不会 | 不会 | **InnoDB 基本不会** | ✅ MySQL 默认 |
| SERIALIZABLE（串行化） | 不会 | 不会 | 不会 | 性能最差 |

```sql
-- 查看与设置
SELECT @@tx_isolation;                                                   -- MySQL 5.7
SELECT @@transaction_isolation;                                          -- MySQL 8.0
SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;
```

### 3.3 三种"读"的问题，用一句话场景记

| 问题 | 一句话 | 场景 |
| --- | --- | --- |
| 脏读 | 读到了**别人还没提交**的数据 | A 转账给 B 还没提交，B 就看到了余额增加，结果 A 回滚了 |
| 不可重复读 | **同一事务内**两次读同一行，结果不一样（别人改了并提交） | 统计报表算到一半，金额被另一个事务改了 |
| 幻读 | **同一事务内**两次查同一个范围，行数变了（别人插入并提交） | 查"待支付订单数"是 3，一会再查变成 4 |

### 3.4 MySQL RR 的关键细节（面试加分点）

MySQL 的 RR 通过 **MVCC（快照读）+ 间隙锁（当前读）** 实现，所以：

- **普通 SELECT（快照读）**：整个事务看到的是开始时的快照，别人新插入的行看不到 → 看起来没幻读。
- **UPDATE / DELETE / SELECT ... FOR UPDATE（当前读）**：读的是最新数据 → **能看到别人刚插入的行**。

```sql
-- 事务 A（RR）
START TRANSACTION;
SELECT COUNT(*) FROM orders WHERE status = 'PAID';     -- 假设 10 条（快照）
-- 事务 B 插入一条 PAID 并提交
SELECT COUNT(*) FROM orders WHERE status = 'PAID';     -- 仍是 10（快照读）
UPDATE orders SET amount = amount WHERE status = 'PAID';  -- 当前读！会改到 11 条
SELECT COUNT(*) FROM orders WHERE status = 'PAID';     -- 现在变成 11 了
```

**所以"RR 能解决幻读"这个说法不严谨**：快照读下看不到，但当前读会看到。测试写"并发插入后统计"的用例时，如果用例里有 UPDATE，就会看到多出来的行 —— 这不是 bug，是语义。

### 3.5 重复提交与数据库的关系（自查 Q2 的一半）

重复提交能不能被拦住，取决于三层，**数据库是最后一层**：

| 层 | 机制 | 失败表现 |
| --- | --- | --- |
| 前端 | 按钮置灰、防抖 | 绕过前端直接打接口就失效 |
| 应用 | 先查后插、分布式锁、Token 校验 | 并发下"查"和"插"之间有窗口 → 失效 |
| **数据库** | **唯一索引 / 乐观锁（version）** | 这才是唯一可靠的兜底 |

```sql
-- 乐观锁更新，version 不匹配就更新 0 行
UPDATE coupon SET status='USED', version = version + 1
WHERE id = 100 AND status='UNUSED' AND version = 3;
-- 影响行数 0 → 说明被别人抢先了，业务应返回"已领取"
```

**测试要验的**：并发 10 次，数据库最终只有 1 条订单 / 1 次扣减。断言看 `ROW_COUNT()` 和表里的记录数。

---

## 4. 测试场景应用：用 SQL 造数、断言、对账

### 4.1 造数据：直接写库 vs 走接口

| 方式 | 优点 | 缺点 | 什么时候用 |
| --- | --- | --- | --- |
| 走接口造 | 符合业务规则、触发完整链路 | 慢、受限（不能造非法状态）、依赖环境 | 验证主流程 |
| 直接写库 | 快、能造任意状态、可批量 | 绕过校验（可能造出脏数据）、字段多易漏 | 准备前置条件、造边界状态 |

**原则**：**前置数据能直接写库就写库，被测行为必须走接口。** 因为你要测的是"下单"，不是"造一个已支付订单"。

```sql
-- 批量造 1000 条待支付订单（用序号表填充）
INSERT INTO orders (order_no, user_id, status, amount, created_at)
SELECT CONCAT('O-GEN-', LPAD(n, 6, '0')), 1001, 'PENDING_PAY',
       100 + n, DATE_SUB(NOW(), INTERVAL n MINUTE)
FROM (
  SELECT @row := @row + 1 AS n
  FROM information_schema.columns a, information_schema.columns b
  LIMIT 1000
) t, (SELECT @row := 0) r;
```

造完记得清理，否则污染环境：

```sql
DELETE FROM orders WHERE order_no LIKE 'O-GEN-%';
```

**造数据的三个纪律**（写进团队规范）：

1. **加可识别前缀**（`O-GEN-`、`qa_`），否则以后不知道哪些是测试数据。
2. **记录造数脚本**，能重复执行、能回滚。
3. **优先用独立账号/独立商品**，别动公共数据（否则别人的用例会挂）。

### 4.2 核心：用 SQL 做数据断言

**这是测开和"只会点页面"的分水岭。** 接口返回 200 只证明"没报错"，库里的状态才证明"做对了"。

```python
# 一个可直接用的断言写法（pymysql / mysql-connector 都可以）
import pymysql

DB = pymysql.connect(host="127.0.0.1", port=3306, user="qa", password="***",
                     database="shop", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def query_one(sql: str, args: tuple = ()) -> dict | None:
    with DB.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_create_order_persisted(api, base_url):
    # 1. 走接口创建订单
    resp = api.post(f"{base_url}/api/orders", json={"sku_id": 1001, "num": 2})
    assert resp.status_code == 200, resp.text
    order_no = resp.json()["data"]["order_no"]

    # 2. 查库确认落库（关键：用接口返回的 order_no 去查，不要用自增 id）
    row = query_one("SELECT order_no, user_id, status, num FROM orders WHERE order_no = %s", (order_no,))
    assert row is not None, f"订单没有落库: {order_no}"
    assert row["status"] == "PENDING_PAY"
    assert row["num"] == 2
```

**这个模式可以复制到所有写接口**：返回成功 → 查库 → 断言字段值 → 断言关联表。

### 4.3 扣库存：验证"库存真的减了，且没有超卖"

```sql
-- 扣库存的正确写法（带条件，防止扣成负数）
UPDATE stock SET qty = qty - 1, version = version + 1
WHERE sku_id = 1001 AND qty >= 1;

-- 检查影响行数：0 表示库存不足，业务必须返回失败
SELECT ROW_COUNT();
```

```python
def test_stock_deduct(api, base_url):
    before = query_one("SELECT qty FROM stock WHERE sku_id = 1001")["qty"]
    r = api.post(f"{base_url}/api/orders", json={"sku_id": 1001, "num": 2})
    assert r.status_code == 200
    after = query_one("SELECT qty FROM stock WHERE sku_id = 1001")["qty"]
    assert after == before - 2, f"库存扣减错误: {before} -> {after}"


def test_no_oversell(api, base_url):
    """库存 1 件，并发 10 个请求，只能成功 1 个。"""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(
            lambda _: api.post(f"{base_url}/api/orders", json={"sku_id": 1002, "num": 1}).status_code,
            range(10)))
    assert results.count(200) == 1, f"超卖了: {results}"
    assert query_one("SELECT qty FROM stock WHERE sku_id = 1002")["qty"] == 0
```

**这是最经典的并发缺陷，也是最容易被漏测的**：单条用例跑一百遍都不会暴露，必须并发。

### 4.4 对账：接口返回 vs 数据库

```python
def test_order_list_consistent_with_db(api, base_url, user_id=1001):
    """列表接口返回的条数和金额，必须和库里一致。"""
    api_rows = api.get(f"{base_url}/api/orders", params={"user_id": user_id, "status": "PAID"}).json()["data"]

    db_row = query_one("""
        SELECT COUNT(*) AS cnt, IFNULL(SUM(amount),0) AS total
        FROM orders WHERE user_id = %s AND status = 'PAID'
    """, (user_id,))

    assert len(api_rows) == db_row["cnt"], "条数不一致"
    assert sum(float(r["amount"]) for r in api_rows) == float(db_row["total"]), "金额不一致"
```

对账类断言最适合做成**每日定时跑**的用例，比人工抽查有效得多。

---

## 5. 【了解即可】：慢 SQL、索引失效、连接数、EXPLAIN

### 5.1 EXPLAIN 只看四列就够

```sql
EXPLAIN SELECT o.order_no, u.nickname
FROM orders o JOIN users u ON u.id = o.user_id
WHERE o.status = 'PENDING_PAY' AND o.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY o.created_at DESC LIMIT 20;
```

| 列 | 看什么 | 判断 |
| --- | --- | --- |
| `type` | 访问方式 | `const/eq_ref/ref/range` 好；**`ALL` 全表扫描、`index` 全索引扫描**要警惕 |
| `key` | 实际用的索引 | **NULL = 没走索引** |
| `rows` | 预估扫描行数 | 越大越危险，和实际返回行数对比 |
| `Extra` | 额外动作 | `Using filesort`（排序没走索引）、`Using temporary`（用了临时表，GROUP BY 常见）、`Using index`（覆盖索引，最好） |

**测试怎么用**：接口慢 → 拿到它执行的 SQL（开慢查询日志或让开发给你） → EXPLAIN → 看 type 是不是 ALL、key 是不是 NULL。**带着这个结论去找开发，比说"接口慢"有效十倍。**

```sql
-- 开慢查询日志
SET GLOBAL slow_query_log = ON;
SET GLOBAL long_query_time = 1;
SHOW VARIABLES LIKE 'slow_query_log_file';
```

### 5.2 索引失效的六个常见原因

| 原因 | 反例 | 正确写法 |
| --- | --- | --- |
| 字段上用函数 | `WHERE DATE(created_at) = '2026-10-29'` | `WHERE created_at >= '2026-10-29' AND created_at < '2026-10-30'` |
| 隐式类型转换 | `WHERE order_no = 123`（order_no 是 varchar） | `WHERE order_no = '123'` |
| 前导模糊 | `LIKE '%abc'` | `LIKE 'abc%'`（或者上搜索引擎） |
| OR 连接非索引列 | `WHERE a=1 OR b=2`（b 无索引） | 拆成两个查询 union |
| 联合索引不满足最左前缀 | 索引 `(user_id, created_at)`，却 `WHERE created_at > ...` | 补 `user_id` 条件 |
| 用 `!=` / `NOT IN` | `WHERE status != 'PAID'` | 枚举取反或改条件 |

**测试的实际价值**：你造的数据让接口变慢了，先排查是不是自己造的数据踩了索引（比如传了个超长字符串、或者传了数字导致隐式转换）。**别一慢就提性能 bug。**

### 5.3 连接数耗尽

```
ERROR 1040 (HY000): Too many connections
```

```sql
SHOW VARIABLES LIKE 'max_connections';         -- 上限，默认 151
SHOW STATUS LIKE 'Threads_connected';          -- 当前连接数
SHOW STATUS LIKE 'Max_used_connections';       -- 历史峰值
SHOW PROCESSLIST;                              -- 谁在占连接（看 Command 是 Sleep 的就是空闲占用）
```

**测试场景真相**：`pytest -n 32` 并行跑用例时，每个 worker 一个连接池，很容易把测试库连接打满。**看到 `Too many connections` 先查自己的并行数和连接池配置，别急着提 bug。**

---

## 6. 自查清单逐条作答（Q1–Q2）

### Q1. 查出最近 7 天创建、状态为「待支付」的订单，按创建时间倒序，含用户昵称

```sql
SELECT
    o.order_no,
    o.status,
    o.amount,
    o.created_at,
    u.nickname
FROM orders AS o
INNER JOIN users AS u ON u.id = o.user_id
WHERE o.status = 'PENDING_PAY'
  AND o.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY o.created_at DESC;
```

**口述时主动补充这四点**（这是把答案从"背 SQL"变成"懂业务"的关键）：

1. **为什么 INNER JOIN**：只查有对应用户的订单。如果要包含"用户被删了但订单还在"的脏数据，改 LEFT JOIN 并接受 nickname 为 NULL。
2. **7 天是滚动还是自然日**：`DATE_SUB(NOW(), INTERVAL 7 DAY)` 是滚动 168 小时；如果业务说"最近 7 个自然日"，要用 `DATE_SUB(CURDATE(), INTERVAL 7 DAY)`。**这里差一整天，对账时会暴露。**
3. **时间字段要能走索引**：`created_at >= ...` 是范围查询可以走索引，但**不要写成 `DATE(created_at) >= ...`**，那样索引失效。
4. **分页要加唯一列**：`ORDER BY o.created_at DESC, o.id DESC`，否则同一秒的订单顺序不稳定，翻页会重复。

### Q2. 事务隔离级别有哪几种？重复提交用例和数据库的什么机制有关？

**隔离级别四种**：READ UNCOMMITTED、READ COMMITTED、REPEATABLE READ（MySQL 默认）、SERIALIZABLE。对应解决脏读、不可重复读、幻读三种问题（见 §3.2）。

**重复提交与数据库的关系**，答三层：

1. **唯一索引**：`order_no` / `request_id` 上建唯一索引，第二个请求插入时直接报 `Duplicate entry`。这是**唯一可靠的最后防线**，因为应用层的"先查后插"在并发下必有窗口。
2. **乐观锁/版本号**：`UPDATE ... SET version = version + 1 WHERE version = N`，影响行数为 0 就说明被抢先了，适用于扣库存、改状态。
3. **事务**：把"扣库存 + 建订单 + 发券"放进一个事务，任一步失败全回滚，避免"扣了库存没建订单"这种半成品。

**加分回答**：重复提交的测试要能区分"应该失败"和"应该幂等成功"两种情况 —— 用户重复提交同一个订单，正确行为是**返回第一次的结果**（幂等），不是报错也不是建两单。所以要断言"两次返回同一个 order_id，且库里只有一条记录"。

---

## 7. 动手清单

- [ ] 用 `LEFT JOIN ... WHERE 右表.id IS NULL` 跑一遍你们测试环境，找出孤儿数据。
- [ ] 给一个写接口补上"返回 → 查库 → 断言字段"的用例，替换掉只看 status_code 的写法。
- [ ] 用 10 并发打一次下单/领券接口，看库里产生几条记录。
- [ ] 拿一条慢接口的 SQL 跑 EXPLAIN，看 type 和 key 两列，带着结论找开发。
