# 测试开发-Redis与缓存篇

> 对应清单：Redis 与缓存【必须掌握】全部
> 对应自查：Q3（接口创建了订单但查不到，排查步骤）
> 说明：缓存三大问题的**通用测试方法**在《系统设计意识篇》§1 已展开，本篇不重复，只讲 **Redis 这一层的具体操作**：用什么结构、怎么连、怎么查、怎么造、怎么验。

---

## 0. 先定位：测开挖 Redis 是为了什么

| 场景 | 具体动作 |
| --- | --- |
| 查数据对不对 | `GET` / `HGETALL` 看缓存里到底是旧值还是新值 |
| 造测试状态 | 直接 `HSET` 改会员等级、篡改余额、塞一个过期的验证码 |
| 验证过期逻辑 | `TTL` 看剩余时间、`DEL` 模拟过期 |
| 验证缓存是否生效 | 比对缓存命中前后的响应耗时、看 `keyspace_hits` |
| 排查"接口查不到" | 确认是不是读到了旧的缓存 |

一句话：**数据库是"最终真相"，Redis 是"接口实际读到的值"，两者不一致就是 bug。**

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 五种结构选型 | 熟练 | 面试必问，且看 key 就能反推业务 |
| redis-cli 常用命令 | 熟练 | 每天用 |
| 验证码/会话/排行榜的实现 | 会用 | 对应 String/Hash/ZSet |
| 缓存一致性验证 | 熟练 | 本篇核心 |
| 三大问题 | 能讲清（系统设计篇已展开） | 穿透/击穿/雪崩 |
| RDB/AOF | 知道名字和作用 | 重启后数据还在不在 |

---

## 1. 五种数据结构：选型就是"看业务要什么"

| 结构 | 一句话 | 典型用途 | 为什么是它 |
| --- | --- | --- | --- |
| **String** | 一个 key 一个值 | 会话 token、验证码、计数器、分布式锁 | 单值、可设 TTL、`INCR` 原子自增 |
| **Hash** | 一个 key 一组字段 | 用户信息、商品详情、配置 | 可以**只改一个字段**，不用整个覆盖 |
| **List** | 有序可重复 | 简单队列、最新消息、操作日志 | `LPUSH` + `BRPOP` 天然 FIFO |
| **Set** | 无序不重复 | 点赞用户、去重、抽奖、共同关注 | `SISMEMBER` O(1) 判存在，自动去重 |
| **ZSet** | 带分数排序 | 排行榜、延迟队列、热度榜 | `ZREVRANGE` 直接拿 Top N，`score` 可存时间戳 |

### 1.1 会话（String）

```
SET  session:uid:1001  "eyJhbGci..."  EX 1800      # 30 分钟过期
GET  session:uid:1001
TTL  session:uid:1001                              # 剩余秒数；-2 表示 key 不存在
DEL  session:uid:1001                              # 注销/强制下线
```

**测试点**：

- 登录后 `TTL` 应该在 1800 左右；调用接口后 TTL 会不会续期（滑动过期 vs 固定过期，要跟开发确认语义）。
- 注销后 key 是否被删（`EXISTS` 返回 0）。
- 同一账号在新设备登录，旧 session 是否被踢（如果 key 是 `session:uid:1001` 单 key，新登录会覆盖旧值 → 旧 token 立即失效，这是"单点登录"的实现）。

### 1.2 验证码（String + TTL，最经典的组合）

```
SET  sms:code:13800001111  "4821"  EX 300          # 5 分钟有效
GET  sms:code:13800001111
TTL  sms:code:13800001111
```

**测试必验的五点**（每一点都能提 bug）：

| 验证点 | 怎么测 | 常见缺陷 |
| --- | --- | --- |
| 过期后不可用 | 等 5 分钟，或用 `EXPIRE key 1` 强制快过期 | 过期了还能用（校验时没查 TTL） |
| 用过一次就失效 | 用同一验证码提交两次 | 第二次还能成功（可重放） |
| 发送频率限制 | 连点 10 次发送 | 无限发（短信轰炸/费用损失） |
| 错误次数限制 | 连续输错 5 次 | 无限试错（可爆破 6 位验证码） |
| 验证码和手机号绑定 | 用 A 手机收到的码去验 B 手机 | 串号（key 设计成 `sms:code` 没带手机号） |

**造数命令**（比等 5 分钟高效得多）：

```bash
# 造一个"即将过期"的验证码，用来测过期逻辑
redis-cli SET sms:code:13800001111 "4821"
redis-cli EXPIRE sms:code:13800001111 2      # 2 秒后过期

# 造一个"已过期"的（或直接删）
redis-cli DEL sms:code:13800001111
```

### 1.3 用户信息 / 会员状态（Hash）

```
HSET  user:1001  nickname "张三"  vip_level 0  balance 100
HGET  user:1001  vip_level
HGETALL user:1001
HSET  user:1001  vip_level 3                 # 只改一个字段，其他不动
```

**为什么用 Hash 不用 String**：用户信息有 20 个字段，改一个昵称时 String 要整个序列化覆盖（有并发覆盖风险），Hash 只改一个字段。

**测试场景：篡改会员状态，验证系统兜底**（清单里明确要求的）

```bash
# 把普通用户改成 VIP
redis-cli HSET user:1001 vip_level 3
```

**这时候要看系统怎么反应，三种结果对应三种质量**：

| 结果 | 说明 | 判定 |
| --- | --- | --- |
| 立刻生效，能享受 VIP 权益 | 服务端**完全信任缓存** | ❌ 严重安全问题：改缓存就能提权 |
| 不生效，仍按数据库的身份处理 | 服务端以 DB 为准，缓存只做展示加速 | ✅ 正确设计 |
| 生效但有审计日志/风控 | 有兜底和可追溯 | ✅ 可接受，但要确认权限校验在服务端 |

```bash
# 更强的攻击：改余额
redis-cli HSET user:1001 balance 999999
```

**测试结论怎么写**：如果改缓存能改出钱/权限，直接按"高危安全缺陷"提，附上复现命令。这不是"缓存没同步"的小问题，是**权限模型设计错误**。

### 1.4 排行榜（ZSet）

```
ZADD    rank:2026-10 100 user:1001        # 加分数
ZINCRBY rank:2026-10 10  user:1001        # 累加
ZREVRANGE rank:2026-10 0 9 WITHSCORES     # Top 10（从高到低）
ZRANK   rank:2026-10 user:1001            # 我的名次（从 0 开始）
```

**测试点**：

- 同分时的排序规则（`ZREVRANGE` 同分按成员字典序，业务常要求"先达到的先排前面" → 需要把时间戳编进 score，如 `score = 分数 * 10^10 + (最大时间戳 - 达成时间)`）。**这个坑真实存在，且很难发现。**
- 名次是从 0 还是 1 开始（接口返回给用户的"第 N 名"要 +1）。
- 榜单过期与重算。
- 并发加分是否丢失（`ZINCRBY` 是原子的，不会；但"先 `ZSCORE` 读出来再 `ZADD` 写回去"会丢）。

### 1.5 队列 / 最新消息（List）

```
LPUSH  msg:uid:1001  "新消息1"        # 头插
LRANGE msg:uid:1001 0 9               # 取最新 10 条
LTRIM  msg:uid:1001 0 99              # 只保留 100 条（防止无限增长）
RPOP   queue:task                     # 消费（FIFO）
```

**测试点**：`LTRIM` 漏写 → key 无限增长 → 内存爆（这是"内存泄漏"的一种形态）。定期跑 `MEMORY USAGE key` 看单个 key 的大小。

### 1.6 选型速查表

```
要排序取 Top N     → ZSet
要 O(1) 判断存在   → Set
要只改部分字段     → Hash
要先进先出         → List
其余单值 + 过期    → String
```

---

## 2. 缓存三大问题（Redis 层怎么观测）

概念在系统设计篇讲过，这里只补**测开能动手的部分**：

| 问题 | Redis 层的观测手段 | 造场景的命令 |
| --- | --- | --- |
| **穿透**（查不存在的数据） | 看 `INFO stats` 的 `keyspace_misses` 是否随请求量线性暴涨 | `DEL` 掉一个不存在商品的 key，然后打 1000 次 |
| **击穿**（热点 key 过期瞬间） | 看某个 key 的 TTL，卡在快过期时并发打 | `EXPIRE hot:sku:1001 1` 然后等 1 秒并发 500 请求 |
| **雪崩**（大量 key 同时过期） | `TTL` 抽样看是否集中 | 批量 `EXPIRE` 成同一个值，或直接 `FLUSHDB` |

```bash
# 命中率：hits / (hits + misses)，正常应该 > 90%
redis-cli INFO stats | Select-String "keyspace_hits|keyspace_misses"

# 实时观察（每秒一行，看 qps 和 key 数变化）
redis-cli --stat

# 看哪些 key 快过期（抽样，生产慎用 KEYS）
redis-cli --scan --pattern "hot:*" | ForEach-Object { "$_ $((redis-cli TTL $_))" }
```

> `KEYS *` 会阻塞 Redis（O(n) 全库扫描），**测试环境也别在压测时用**，用 `SCAN` 或 `--scan` 代替。这条本身就是一个"你懂 Redis"的信号。

### 2.1 持久化：RDB / AOF

| | RDB | AOF |
| --- | --- | --- |
| 是什么 | 定时把内存**快照**存成文件 | 追加写**每条命令**日志 |
| 数据安全 | 会丢最后一次快照之后的数据 | 丢失少（取决于 `appendfsync`） |
| 恢复速度 | 快 | 慢（要重放命令） |
| 文件大小 | 小 | 大 |

**测试只关心两件事**：

1. **重启后数据还在不在**：`DEBUG RELOAD` 或重启容器，看会话/验证码是否丢失。如果缓存丢了业务能兜底（回源 DB），说明设计是好的；如果直接报错，就是缺陷。
2. **丢多少数据能接受**：RDB 每 5 分钟一次，意味着最多丢 5 分钟数据。**如果业务把"不能丢"的东西放在 Redis，这就是设计问题** —— 该落库的落库。

---

## 3. 测试场景应用（清单里的三条）

### 3.1 用 redis-cli 查数、造数

```bash
# 连（有密码时）
redis-cli -h 127.0.0.1 -p 6379 -a "your-password" --no-auth-warning

# 常用：看 key 存不存在、类型、大小、剩余时间
EXISTS user:1001
TYPE   user:1001
MEMORY USAGE user:1001
TTL    sms:code:13800001111

# 看所有 key（测试环境小库可以用，生产用 SCAN）
SCAN 0 MATCH "order:*" COUNT 100

# 造数：直接塞一条订单缓存
SET  order:20261029001 '{"order_no":"20261029001","status":"CREATED"}'  EX 3600

# 改数：篡改状态
SET  order:20261029001 '{"order_no":"20261029001","status":"PAID"}'

# 清数：删掉让缓存回源
DEL  order:20261029001

# 危险操作（只在测试环境）
FLUSHDB          # 清当前库
FLUSHALL         # 清所有库 —— 千万别在生产按这个
```

**安全提示**：`FLUSHALL` 前先 `DBSIZE` 看一眼，确认连的是测试环境（`INFO server` 里看 `tcp_port` 和 `run_id`）。我在真实项目里见过测试脚本连错环境把线上缓存清空的案例 —— 代价是当天全站缓存穿透。

### 3.2 验证码过期逻辑（完整用例设计）

```python
import time
import redis

r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)


def test_sms_code_expired(api, base_url, phone="13800001111"):
    # 1. 走接口发验证码
    api.post(f"{base_url}/api/sms/code", json={"phone": phone})
    code = r.get(f"sms:code:{phone}")
    assert code is not None, "验证码没有写入 Redis"

    # 2. 断言 TTL 在合理范围（配置是 300s）
    ttl = r.ttl(f"sms:code:{phone}")
    assert 250 <= ttl <= 300, f"TTL 异常: {ttl}"

    # 3. 强制让它过期（比等 5 分钟快）
    r.expire(f"sms:code:{phone}", 1)
    time.sleep(1.2)

    # 4. 过期后再用，必须失败
    resp = api.post(f"{base_url}/api/login/sms", json={"phone": phone, "code": code})
    assert resp.json()["code"] != 0, "验证码过期后仍然可用"


def test_sms_code_single_use(api, base_url, phone="13800001112"):
    api.post(f"{base_url}/api/sms/code", json={"phone": phone})
    code = r.get(f"sms:code:{phone}")

    first = api.post(f"{base_url}/api/login/sms", json={"phone": phone, "code": code})
    assert first.json()["code"] == 0
    assert r.exists(f"sms:code:{phone}") == 0, "验证码用过之后没有删除"

    second = api.post(f"{base_url}/api/login/sms", json={"phone": phone, "code": code})
    assert second.json()["code"] != 0, "同一个验证码可以重复使用（可重放）"
```

`r.expire(key, 1)` 这个技巧把"等 5 分钟"变成"等 1 秒"，是验证过期逻辑的标准手法。

### 3.3 缓存与数据库一致性（清单里明确要求的用例设计）

**只测一个方向是不够的，两个方向都要测：**

| 方向 | 用例 | 期望 |
| --- | --- | --- |
| 改库后读 | 更新 DB → 立刻调查询接口 | 返回新值（缓存被更新或删除） |
| 改库后回源 | 更新 DB → 手动 `DEL` 缓存 → 调查询接口 | 返回新值（说明回源正确） |
| 并发读写 | 一边高频改、一边高频读 | 短时间内可能旧值，但**最终一致**，且不能长期不一致 |
| 缓存与库双写失败 | 更新 DB 成功、删缓存失败（可 mock） | 有兜底（延迟双删、消息补偿），不能永久脏 |

```python
def test_cache_consistency(api, base_url, r, order_id):
    """改库之后，缓存有没有正确更新/失效。"""
    # 1. 先读一次，让缓存建立
    old = api.get(f"{base_url}/api/orders/{order_id}").json()["data"]
    assert r.exists(f"order:{order_id}") == 1, "读接口没有写缓存（或 key 设计不同）"

    # 2. 改库（绕过接口直接改，确保一定会变）
    update_db("UPDATE orders SET status='PAID' WHERE order_no=%s", (order_id,))

    # 3. 再读。有缓存没失效的话这里会返回旧值 → 就是缺陷
    new = api.get(f"{base_url}/api/orders/{order_id}").json()["data"]

    # 4. 允许的延迟：业务通常接受秒级，不允许的是"永久脏"
    for _ in range(5):
        if new["status"] == "PAID":
            break
        time.sleep(1)
        new = api.get(f"{base_url}/api/orders/{order_id}").json()["data"]

    assert new["status"] == "PAID", f"改库 5 秒后缓存仍是旧值（脏读）: {new}"
```

**这个用例的价值**：它是唯一能发现"更新 DB 但忘了删缓存"的用例。而这类 bug 线上表现是"用户改了地址，刷新还是旧的"，用户会反复投诉。

---

## 4. 自查 Q3 完整作答：接口创建了订单，但查询接口查不到

这是本批最值钱的一道题，考的是**数据链路排查能力**。按层排查，每步都要给出"怎么确认"。

### 排查顺序（从近到远，成本从低到高）

| 步 | 查什么 | 怎么查 | 结论指向 |
| --- | --- | --- | --- |
| 1 | **创建接口真的成功了吗** | 看响应码 + 业务码 + 响应体里的 `order_no`/`id` | 如果业务码不是 0，问题在创建侧，不用往下查 |
| 2 | **数据有没有落库** | 用响应体里的 `order_no` 直接 `SELECT` | 没有 → 事务回滚了 / 落到了别的库 / 异步没执行 |
| 3 | **查的是主库还是从库** | 对比主从：`SELECT` 主库、`SELECT` 从库 | **主从延迟**是最常见原因（见下） |
| 4 | **缓存里是什么** | `GET order:xxx` / `HGETALL` | 缓存是旧值或空 → 缓存没有失效，或回源逻辑错 |
| 5 | **查询接口连的是不是同一个数据源** | 看两个服务的配置（订单服务库 vs 查询服务库） | 分库分表路由错 / 订单服务写了 A 库、查询服务读 B 库 |
| 6 | **查询条件对不对** | 看 SQL：`user_id`、`status`、时间范围、分页 | 查到了但被过滤掉（比如默认只查"未删除"、只查自己的订单） |
| 7 | **接口是否走了异步/最终一致** | 看有没有 MQ 同步链路 | 写完 CQRS/ES 的库还没同步 |

### 最关键的一步：主从延迟

```
创建订单 → 写主库（成功返回） → 立刻查询 → 读从库（复制还没完成）→ 查不到
```

**这是"创建了查不到"的头号原因**，尤其在读写分离的架构里。

**怎么确认**：

```sql
SHOW SLAVE STATUS\G        -- 看 Seconds_Behind_Master，>0 就是有延迟
SHOW MASTER STATUS;        -- 主库位点
```

```bash
# 或者在业务上验证：创建后立刻查，延迟 100ms 再查
for i in 1 2 3 4 5; do
  curl -s "$BASE/api/orders/$ORDER_NO" | head -c 100; echo
  sleep 0.1
done
```

**如果 0.1 秒后就查到了 → 就是主从延迟**，属于"最终一致"，要跟产品确认延迟是否可接受（通常几百毫秒可以，秒级以上要提）。

**如果永远查不到 → 不是延迟，是写错地方了**，继续查第 5、6 步。

### 完整话术（可以直接照着说）

> 我会按"创建侧 → 存储侧 → 读取侧"三层排查。
> **第一**，先确认创建接口真的成功了：不只看 HTTP 200，要看业务码和响应体里的订单号，拿这个订单号后面所有步骤都用得上。
> **第二**，拿订单号直接查库（`SELECT ... WHERE order_no=?`）。查不到说明没落库 —— 可能是事务回滚、写到了别的库（分库分表路由）、或者写操作是异步的还没执行。
> **第三**，如果库里有但接口查不到，先怀疑**主从延迟**：读写分离下写主库、读从库，复制需要时间。用 `SHOW SLAVE STATUS` 看 `Seconds_Behind_Master`，或者间隔 100ms 连续查几次，如果延迟一小会儿就能查到，就是最终一致而非 bug。
> **第四**，再查缓存：`GET order:xxx` 看是空值还是旧值。空值可能是缓存没建立或读接口回源失败；旧值说明改库后没删缓存。
> **第五**，最后查数据源和查询条件：两个服务是不是连的同一个库、查询 SQL 有没有被 `user_id`/`status`/逻辑删除条件过滤掉。
> 这个顺序的考虑是**从成本低的开始**：查库最快、最有信息量，缓存和配置排查成本高，放后面。

---

## 5. 动手清单

- [ ] 用 `redis-cli TTL` 查一遍你们系统的会话/验证码 key，确认过期时间符合设计。
- [ ] 用 `EXPIRE key 1` 造一次过期，验证过期后的接口行为。
- [ ] `HSET` 篡改一次会员等级/余额，看服务端是信任缓存还是信任 DB。
- [ ] 写一条"改库后立刻读"的一致性用例，看能不能抓到脏读。
- [ ] `redis-cli INFO stats` 看一次命中率，低于 90% 就去看是哪些 key 在穿透。
