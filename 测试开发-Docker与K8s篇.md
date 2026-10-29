# 测试开发-Docker与K8s篇

> 对应清单：Docker【必须掌握】+ Docker【了解即可】+ K8s【了解即可】全部
> 对应自查：Q6（用 docker 起 MySQL、挂载配置、建库建表、宿主机连上）
> 立场：Docker 对测开的真正价值不是"会启容器"，而是**随时能造一个干净、可复现、测完就扔的测试环境** —— 这是解决"测试环境脏了没人洗"的唯一实用手段。

---

## 0. 先定位：容器能力在测试工作里的三个落点

| 落点 | 具体做法 | 解决什么问题 |
| --- | --- | --- |
| 造干净数据库 | 每次跑用例前起一个一次性 MySQL | 测试库被脏数据污染、用例互相干扰 |
| 造完整依赖环境 | `docker-compose` 一键起"MySQL + Redis + 后端" | 本地复现环境、新人一条命令上手 |
| 造被测服务 | 把自己的 mock 服务打成镜像 | 部署到任意环境、当第三方 mock |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| 镜像/容器、启停、看日志 | 熟练 | 每天 |
| 端口映射、挂载、环境变量 | 熟练 | 配错一个就起不来 |
| Dockerfile | 会写 | 打自己的测试服务 |
| compose | 会用 | 一键起组合环境 |
| 一次性容器隔离测试 | 熟练 | 本篇最值钱的一条 |
| K8s 三件套 + kubectl 四板斧 | 能查能用 | 测试环境排障 |

---

# 第一部分：Docker

## 1. 镜像与容器：一句话说清

```
镜像（Image） = 只读模板（类似"安装光盘"或"类"）
容器（Container） = 镜像跑起来的实例（类似"装好的系统"或"对象"）
一个镜像 → 可以跑 N 个容器（互不影响）
容器里改的东西 → 默认不落回镜像（除非 commit 或挂载）
```

```bash
docker pull mysql:5.7                    # 拉镜像
docker images                            # 本地有哪些镜像
docker run -d --name mysql-test mysql:5.7 # 起容器（-d 后台）
docker ps                                # 跑着的容器
docker ps -a                             # 包括已停止的（排查"容器怎么没了"必看）
docker stop mysql-test                   # 停止
docker rm mysql-test                     # 删除容器
docker rmi mysql:5.7                     # 删除镜像
```

## 2. 三个必须用对的参数

### 2.1 端口映射 `-p 宿主机:容器`

```bash
docker run -d -p 13306:3306 mysql:5.7
#                      ↑宿主机端口  ↑容器内端口
docker port mysql-test          # 查看映射关系
```

**坑**：宿主机端口冲突 → `Error starting userland proxy: Bind for 0.0.0.0:3306 failed: port is already allocated`。改宿主机端口就行（容器内端口不用改）。**这也是为什么测试环境要用非默认端口（3306→13306），避免和本机已装的 MySQL 抢。**

### 2.2 挂载 `-v 宿主机路径:容器路径`

```bash
-v /data/mysql/conf:/etc/mysql/conf.d      # 挂配置目录（改配置不用重建镜像）
-v /data/mysql/data:/var/lib/mysql          # 挂数据目录（容器删了数据还在）
-v $(pwd)/init:/docker-entrypoint-initdb.d  # 挂初始化脚本（首次启动自动执行）
```

| 挂载目的 | 好处 | 坑 |
| --- | --- | --- |
| 配置目录 | 改配置不用重建容器 | 宿主机文件权限不对 → 容器内读不到 |
| 数据目录 | 数据持久化 | **宿主机目录非空且不是 MySQL 格式 → 起不来**；Windows 挂载有文件锁/权限问题 |
| 初始化脚本 | 自动建库建表造数 | **只在数据目录为空时执行一次**，第二次起就不跑了 |

### 2.3 环境变量 `-e`

```bash
-e MYSQL_ROOT_PASSWORD=123456      # MySQL 必须有，否则拒绝启动
-e MYSQL_DATABASE=qa_shop          # 首次启动自动建库
-e MYSQL_USER=qa -e MYSQL_PASSWORD=qa123   # 自动建用户
```

**纪律**：密码不要写进 Dockerfile，用 `-e` 或 `--env-file`，并且 `--env-file` 的文件加进 `.gitignore`。

## 3. 排查容器问题的四条命令

```bash
docker logs -f --tail 100 mysql-test       # 看日志（-f 实时跟，--tail 只看最后 100 行）
docker exec -it mysql-test bash            # 进容器（没有 bash 用 sh）
docker inspect mysql-test                  # 看全部配置：IP、挂载、环境变量、退出码
docker stats                               # 实时资源占用（CPU/内存/网络）
```

**容器起不来时的排查顺序**（和 K8s 那套一模一样）：

```
docker ps -a 看 STATUS（Exited (1)? Exited (137)?）
  → docker logs 看最后几十行（最常见的错误都在这里）
  → docker inspect 看 State.ExitCode 和 Mounts 是否正确
  → docker exec 进去手动跑一遍启动命令
```

| 退出码 | 含义 | 典型原因 |
| --- | --- | --- |
| 0 | 正常退出 | 前台进程跑完就退了（没加 `-d` 或 CMD 写错） |
| 1 | 应用报错 | 配置错、端口占用、依赖缺失 |
| 137 | 128+9（SIGKILL） | **被 OOM 杀** 或 `docker stop` 超时强杀 → 调大内存限制 |
| 143 | 128+15（SIGTERM） | 正常 `docker stop` |

## 4. 写一个 Dockerfile：把自己的测试服务打进去

```dockerfile
# 一个最小可用的测试靶子服务镜像
FROM python:3.10-slim

WORKDIR /app

# 先拷依赖再拷代码 → 利用 layer 缓存，改代码时不用重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY mock_server/ ./mock_server/

# 不用 root 跑（生产要求，测试镜像也建议养成习惯）
RUN useradd -m -u 1000 app
USER app

EXPOSE 5057
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5057/api/health')" || exit 1

CMD ["python", "-m", "mock_server.app"]
```

```bash
docker build -t qa-mock-server:0.1 .
docker run -d --name mock -p 5057:5057 qa-mock-server:0.1
docker logs -f mock
```

**四个值得记住的点**：

1. **依赖单独 COPY + RUN**：代码改动不会让依赖层失效，构建从几分钟降到几秒。
2. **`--no-cache-dir`**：减小镜像体积。
3. **HEALTHCHECK**：容器"跑着"不等于"服务可用"，健康检查才有意义。
4. **不用 root**：养成习惯，避免挂载目录权限问题。

## 5. docker-compose：一键起组合环境

```yaml
# docker-compose.yml
services:
  mysql:
    image: mysql:5.7
    container_name: qa-mysql
    ports:
      - "13306:3306"
    environment:
      MYSQL_ROOT_PASSWORD: "123456"
      MYSQL_DATABASE: "qa_shop"
    volumes:
      - ./mysql/conf:/etc/mysql/conf.d
      - ./mysql/init:/docker-entrypoint-initdb.d
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-p123456"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "16379:6379"

  mock-server:
    build: .
    ports:
      - "5057:5057"
    depends_on:
      mysql:
        condition: service_healthy     # 等 MySQL 真的能连了再起
    environment:
      DB_HOST: mysql
      DB_PORT: "3306"
```

```bash
docker compose up -d          # 起全部（旧版是 docker-compose up -d）
docker compose ps             # 看状态
docker compose logs -f mysql  # 看某个服务日志
docker compose down -v        # 停并删除数据卷（彻底干净）
```

**`depends_on` + `healthcheck` 是关键**：只写 `depends_on` 只保证"容器启动了"，不保证"MySQL 能连了"，应用会连不上数据库。这是 compose 里最常见的坑。

## 6. 测试里最值钱的用法：一次性干净数据库

**问题**：测试库跑了一周全量回归，里面堆了几万个测试订单、错乱的库存、脏的配置项。某天开始用例随机失败，查一整天发现是数据被污染了。

**解法**：每个测试会话（或每个 CI job）起一个全新的数据库容器，测完销毁。

```python
# conftest.py
import subprocess
import time

import pytest
import pymysql

MYSQL_PORT = 13306


def wait_mysql(port: int, timeout: int = 60):
    """等 MySQL 真的可连接（不能只 sleep，启动时间不确定）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = pymysql.connect(host="127.0.0.1", port=port, user="root",
                                   password="123456", connect_timeout=2)
            conn.close()
            return True
        except Exception:
            time.sleep(1)
    return False


@pytest.fixture(scope="session")
def clean_db():
    name = "qa-mysql-ephemeral"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)     # 清掉上次残留
    subprocess.run([
        "docker", "run", "-d", "--rm", "--name", name,
        "-p", f"{MYSQL_PORT}:3306",
        "-e", "MYSQL_ROOT_PASSWORD=123456",
        "-e", "MYSQL_DATABASE=qa_shop",
        "-v", f"{INIT_SQL_DIR}:/docker-entrypoint-initdb.d",              # 自动建表+基础数据
        "mysql:5.7", "--character-set-server=utf8mb4",
    ], check=True)

    assert wait_mysql(MYSQL_PORT), "MySQL 60s 内未就绪"
    yield f"127.0.0.1:{MYSQL_PORT}"

    subprocess.run(["docker", "rm", "-f", name], capture_output=True)     # --rm 也会删，双保险
```

**这个模式的价值**：

| 收益 | 说明 |
| --- | --- |
| 消除数据污染 | 每次从零开始，用例之间不会互相影响 |
| 消除 flaky | "昨天能过今天不能过"的数据类问题基本消失 |
| 可并行 | 每个 worker 一个容器（不同端口），互不干扰 |
| 可复现 | 任何人任何机器，起出来的库完全一样 |

**代价**：启动 20~40 秒。所以只适合"每个会话/每个 CI job 一次"，不要每条用例都起。

---

# 第二部分：K8s（了解即可，但要知道怎么查）

## 7. 为什么需要容器编排

单机 Docker 解决"跑起来"，但生产有 100 台机器、200 个容器时要解决：

| 问题 | Docker 单机 | K8s |
| --- | --- | --- |
| 容器挂了谁重启 | 没人 | 自动重启 |
| 扩容怎么办 | 手工起 | 改副本数 |
| 服务怎么找到彼此 | 记 IP | Service 提供稳定域名 |
| 发版怎么不停机 | 手工 | 滚动更新 |

## 8. 三个核心对象（理解到这一层就够）

| 对象 | 是什么 | 测试怎么看它 |
| --- | --- | --- |
| **Pod** | 最小调度单位，1~N 个容器共享网络和存储 | `kubectl get pods`，看状态和重启次数 |
| **Deployment** | 管理 Pod 的副本数 + 滚动更新 + 回滚 | `kubectl get deploy`，看期望/就绪副本数 |
| **Service** | 给一组 Pod 提供**固定访问入口** + 负载均衡 | `kubectl get svc`，看 ClusterIP / NodePort |

```
Deployment(order-service, 3 副本)
   ├─ Pod A  ← 自动创建、自动重启
   ├─ Pod B
   └─ Pod C
        ↑
Service(order-svc:8080)  ← 固定入口，把流量分给这三个 Pod
```

**关键认知**：**Pod 的 IP 会变，Service 的地址不变。** 所以配置里永远写 Service 名，不写 Pod IP。

## 9. kubectl 四板斧

```bash
# 1. get：有什么、状态如何
kubectl get pods -n test -o wide          # Pod 列表（-o wide 看 IP 和所在节点）
kubectl get pods -n test -w               # 实时看变化（发版时盯这个）
kubectl get deploy,svc -n test            # Deployment 和 Service
kubectl get events -n test --sort-by=.lastTimestamp | tail -20   # 最近的事件（排障神器）

# 2. describe：为什么是这个状态（最重要的一条）
kubectl describe pod <pod> -n test
# 重点看最后 Events 段落：镜像拉取失败？调度失败？探针失败？OOM？

# 3. logs：应用自己说了什么
kubectl logs <pod> -n test
kubectl logs <pod> -n test --tail=200
kubectl logs <pod> -n test -f                   # 实时跟
kubectl logs <pod> -n test --previous           # ★ 上一个已死容器的日志（CrashLoopBackOff 必用）

# 4. exec：进去手动验证
kubectl exec -it <pod> -n test -- sh
kubectl exec -it <pod> -n test -- curl -s localhost:8080/api/health
```

## 10. Pod 起不来时的排查（带着信息找开发）

| Pod 状态 | 含义 | 先看什么 |
| --- | --- | --- |
| `Pending` | 调度不出去 | `describe` 的 Events：资源不足（Insufficient cpu/memory）、节点选择器不匹配、PVC 挂不上 |
| `ImagePullBackOff` / `ErrImagePull` | 镜像拉不到 | 镜像名/tag 写错、私有仓库没配 `imagePullSecrets`、网络不通 |
| `CrashLoopBackOff` | 启动后反复崩溃 | `logs --previous` 看上一轮日志；`describe` 看退出码和探针配置 |
| `OOMKilled` | 内存超限被杀 | `describe` 里 `Last State: Terminated Reason: OOMKilled ExitCode: 137` → 调大 limits 或查内存泄漏 |
| `Running` 但没就绪（0/1） | 探针没过 | `describe` 看 Readiness probe failed，`exec` 进去手动 `curl` 探针地址 |
| `Terminating` 卡住 | 优雅退出没完成 | finalizer、`terminationGracePeriodSeconds` |

**标准排查顺序**（这三步覆盖 90% 的问题）：

```bash
kubectl get pods -n test                    # 1. 是什么状态
kubectl describe pod xxx -n test            # 2. 看 Events 说了什么
kubectl logs xxx -n test --previous         # 3. 看应用自己报了什么
```

**测开的正确姿势**：**先自己看，带着 Events 里的错误信息去找开发**。说"Pod 起不来"和说"镜像拉取失败，Events 里是 401 Unauthorized，imagePullSecrets 没配" —— 后者能省掉半小时的来回。

---

## 11. 自查 Q6 完整作答：用 docker 起 MySQL、挂载配置、建库建表、宿主机连上

**完整命令链（可以直接照抄改端口密码）：**

```bash
# 1. 准备目录（配置、初始化脚本、数据）
mkdir -p ~/qa-mysql/{conf,init,data}

# 2. 放一个自定义配置（可选，验证挂载生效）
cat > ~/qa-mysql/conf/my.cnf <<'EOF'
[mysqld]
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
max_connections=500
slow_query_log=1
long_query_time=1
EOF

# 3. 放初始化脚本（首次启动自动执行：建库建表 + 基础数据）
cat > ~/qa-mysql/init/01-init.sql <<'EOF'
CREATE DATABASE IF NOT EXISTS qa_shop DEFAULT CHARSET utf8mb4;
USE qa_shop;
CREATE TABLE IF NOT EXISTS orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_no VARCHAR(32) NOT NULL,
  user_id BIGINT NOT NULL,
  status VARCHAR(16) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_order_no (order_no),
  KEY idx_status_created (status, created_at)
) ENGINE=InnoDB;
INSERT INTO orders (order_no, user_id, status, amount)
VALUES ('O-SEED-001', 1001, 'PENDING_PAY', 99.00);
EOF

# 4. 起容器（端口 13306，挂三类目录，设密码和初始库）
docker run -d --name qa-mysql \
  -p 13306:3306 \
  -e MYSQL_ROOT_PASSWORD=123456 \
  -e MYSQL_DATABASE=qa_shop \
  -v ~/qa-mysql/conf:/etc/mysql/conf.d \
  -v ~/qa-mysql/init:/docker-entrypoint-initdb.d \
  -v ~/qa-mysql/data:/var/lib/mysql \
  mysql:5.7

# 5. 等就绪（不要只 sleep，看日志更可靠）
docker logs -f qa-mysql
# 看到 "ready for connections" 两次（一次初始化、一次正常启动）就好了

# 6. 容器内验证：配置有没有生效、库表有没有建好、种子数据在不在
docker exec -it qa-mysql mysql -uroot -p123456 -e "
  SHOW VARIABLES LIKE 'character_set_server';
  SHOW VARIABLES LIKE 'max_connections';
  SHOW DATABASES;
  USE qa_shop; SHOW TABLES; SELECT * FROM orders;"

# 7. 从宿主机连（这才是"从外面能连上"的验证）
mysql -h127.0.0.1 -P13306 -uroot -p123456 -e "SELECT COUNT(*) FROM qa_shop.orders;"
# 没有 mysql 客户端就用 docker：见下面的说明
# 用 Python 连：
# python -c "import pymysql;c=pymysql.connect(host='127.0.0.1',port=13306,user='root',password='123456');print(c)"
```

**验证清单（做完这四项才算真的"起好了"）：**

| 验证项 | 命令 | 期望 |
| --- | --- | --- |
| 容器在跑 | `docker ps` | STATUS 是 `Up` 且没有频繁 `Restarting` |
| 端口映射对 | `docker port qa-mysql` | `3306/tcp -> 0.0.0.0:13306` |
| 配置挂载生效 | `SHOW VARIABLES LIKE 'max_connections'` | 500（不是默认 151） |
| 初始化脚本执行了 | `SHOW TABLES` / `SELECT * FROM orders` | 表和种子数据都在 |
| 宿主机能连 | `mysql -h127.0.0.1 -P13306 ...` | 能查数据 |

**四个必踩的坑，提前说清：**

| 坑 | 现象 | 解法 |
| --- | --- | --- |
| 挂载 `data` 目录时宿主机目录非空 | 容器起不来或初始化被跳过 | 确保第一次挂载时目录为空；**初始化脚本只在 data 为空时执行** |
| 端口冲突 | `port is already allocated` | 换宿主机端口（13306 → 13307） |
| `-e MYSQL_ROOT_PASSWORD` 没设 | 容器直接退出 | MySQL 镜像强制要求设密码，或用 `MYSQL_ALLOW_EMPTY_PASSWORD=yes`（仅本地） |
| Windows 挂载路径 | 路径要用绝对路径且 Docker Desktop 要授权共享盘 | 用 `//c/data/mysql` 或换成命名卷 `-v qa_mysql_data:/var/lib/mysql` |

**如果宿主机没有 mysql 客户端**（很常见），两种替代：

```bash
# 方式 1：进容器里执行（验证的是容器内连接，不是宿主机）
docker exec -it qa-mysql mysql -uroot -p123456 -e "SELECT 1"

# 方式 2：用 Python/Java 从宿主机连（这才等价于"应用能连上"）
python -c "
import pymysql
conn = pymysql.connect(host='127.0.0.1', port=13306, user='root', password='123456', database='qa_shop')
with conn.cursor() as cur:
    cur.execute('SELECT COUNT(*) FROM orders')
    print('orders =', cur.fetchone()[0])
"
```

**完整话术**：

> 我会用 `docker run` 起一个 mysql:5.7，映射宿主机 13306 到容器 3306，用 `-e` 设 root 密码和初始库，`-v` 挂三个目录：`conf` 挂配置、`init` 挂初始化 SQL、`data` 挂数据目录。
> 建库建表我倾向放在 `init/*.sql` 里而不是手动执行 —— 因为 `/docker-entrypoint-initdb.d` 会在数据目录为空时自动跑，**保证每次起出来的库结构一致，这也是 CI 里能复现的前提**。
> 验证分四步：`docker ps` 看状态、`docker port` 看映射、`docker exec ... mysql -e` 看配置和表是否生效、最后从**宿主机**用客户端或 Python 连一次 —— 因为容器内能连不代表宿主机能连，这才对应应用真实的访问路径。
> 测完直接 `docker rm -f`（加 `--rm` 起的话 stop 就自动删），数据不残留，下次从零开始。

---

## 12. 动手清单

- [ ] 用 §11 的命令起一个 MySQL，验证挂载的配置真的生效（改 `max_connections` 看值变没变）。
- [ ] 用 `--rm` 起一个一次性 MySQL，跑一遍用例，然后 `docker stop` 确认自动销毁。
- [ ] 写一个 Dockerfile 把自己的 mock 服务打进去，`HEALTHCHECK` 要能通过。
- [ ] 在测试环境用 `kubectl describe pod` 看一次 Events，对照 §10 的表格认一遍状态。
