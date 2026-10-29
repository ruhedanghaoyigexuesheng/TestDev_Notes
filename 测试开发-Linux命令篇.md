# 测试开发-Linux命令篇

> 对应清单：Linux【必须掌握】全部
> 对应自查：Q4（tail -f / grep -C 5 / ps aux | grep 分别在什么场景用）
> 立场：清单里那句定位非常准 —— **Linux 命令在测试岗位只服务两件事：查日志、看状态**。这两件事做到位，90% 的"环境问题"不用找运维。

---

## 0. 先定位：命令不是背，是"排障组合拳"

| 你要回答的问题 | 组合拳 |
| --- | --- |
| 这个订单在日志里发生了什么 | `grep` 定位 → `grep -C` 看上下文 → `tail -F` 实时跟 |
| 服务是不是还活着 | `ps aux \| grep` → `ss -tlnp` → `curl` 探活 |
| 为什么越来越慢 | `top` → `ps` 排序 → `df` / `du` / `free` |
| 请求到底打到哪台机器 | `curl -v` → `ss` → Nginx 日志 |
| 日志太大翻了半天 | `awk` 按列取 → `sort \| uniq -c` 统计 |

自查分级：

| 内容 | 档位 | 说明 |
| --- | --- | --- |
| `grep` / `tail -f` / `ps` | 熟练 | 每天都在用 |
| `grep -C/-A/-B`、`awk` 取列 | 熟练 | 高效排障的关键 |
| `ss` / `curl -v` | 熟练 | 网络问题第一手 |
| `df/du/free/top` | 会用 | 资源问题 |
| `sed` 替换 | 会用 | 批量处理 |
| `chmod/chown` | 会用 | 权限问题偶发 |

---

## 1. 文件与目录：`cd ls cat tail -f grep find`

### 1.1 最常用的六条

```bash
cd /opt/app/logs            # 进目录
cd -                        # 回上一个目录（在两个目录间来回切，很实用）
ls -lh                      # 带大小、带权限、可读
cat app.log | head -50      # 看开头
tail -n 200 app.log         # 看最后 200 行
tail -f app.log             # 实时跟（Ctrl+C 退出）
```

### 1.2 `tail -f` 的坑：日志轮转后要改用 `tail -F`

| 命令 | 行为 | 什么时候用 |
| --- | --- | --- |
| `tail -f` | 跟着**文件描述符** | 文件不会被轮转时 |
| `tail -F` | 跟着**文件名**，文件被重命名/重建后自动重新打开 | **日志按天切割 → 必须用大写 F** |

**真实场景**：日志每天 0 点切割，你前一天晚上开着 `tail -f` 看，跨过 0 点后就再也不出内容了 —— 因为文件被 mv 走了，你还在跟旧 inode。**`tail -F` 不会断。**

### 1.3 `grep`：从"找行"到"看上下文"

```bash
grep "order_no=O-20261029-001" app.log          # 找行
grep -n "ERROR" app.log                          # 带行号
grep -i "error" app.log                          # 忽略大小写
grep -c "ERROR" app.log                          # 只统计条数
grep -v "healthcheck" app.log                    # 排除（过滤掉探活噪音）
grep -C 5 "O-20261029-001" app.log               # 前后各 5 行 ← 最常用
grep -A 10 "ERROR" app.log                       # 后 10 行（看堆栈）
grep -B 10 "ERROR" app.log                       # 前 10 行（看请求参数）
grep -E "ERROR|WARN|Exception" app.log           # 多关键词
grep -r "skuservice" /opt/app/config/            # 递归搜目录
```

**`-C 5` 为什么最常用**：日志一行通常只有一个时间戳和一句话，真正的信息（请求参数、堆栈、返回值）在上下文里。**只 grep 不加 `-C`，等于只看到"错了"，看不到"为什么错"。**

```bash
# 标准排障动作：一个订单号，要看到它前后的完整链路
grep -C 10 "O-20261029-001" app.log | grep -v healthcheck
```

### 1.4 `find`：按条件找文件

```bash
find /opt/app/logs -name "*.log" -mtime -1              # 1 天内改过的 log
find . -name "*.py" -newermt "2026-10-29 09:00"          # 今天 9 点后改的代码
find /var/log -size +100M                                # 大于 100M 的文件（找吃磁盘的）
find . -type f -name "*.log" -exec ls -lh {} \; | sort -k5 -rh | head   # 大日志排行
find /tmp -name "*.tmp" -mtime +7 -print                 # 先 -print 看一眼，别直接 -delete
```

**纪律**：`find ... -delete` 之前一定先跑 `-print`，确认匹配的是你要删的文件。我见过 `-name "*.log" -delete` 把正在写的日志删掉导致服务异常的例子。

---

## 2. 文本处理：`awk` 和 `sed`（按列取数 + 替换）

### 2.1 `awk`：按列取数 + 简单统计

日志是 tab/空格分隔时，`awk '{print $N}'` 就是最快的取列方式。

```bash
# 取第 9 列（Nginx access.log 里第 9 列是状态码）
awk '{print $9}' access.log | sort | uniq -c | sort -rn | head
# 输出：
#   8231 200
#    142 502
#     37 504

# 按状态码筛出 5xx，并看对应的 URL（第 7 列）
awk '$9 ~ /^5/ {print $9, $7}' access.log | sort | uniq -c | sort -rn | head

# 计算接口耗时平均值（假设第 10 列是耗时）
awk '{sum += $10; n++} END {printf "平均 %.3f ms, 共 %d 条\n", sum/n, n}' access.log

# 指定分隔符（处理 CSV 或 tab 日志）
awk -F'\t' '{print $2, $5}' app.log

# 统计每个用户的请求数（第 1 列是 user_id）
awk '{print $1}' app.log | sort | uniq -c | sort -rn | head -20
```

**测试最常用的三个 `awk` 用法**，记住就够：

1. `awk '{print $N}'` 取列
2. `awk -F'分隔符' '{print $N}'` 指定分隔符
3. `awk '$N ~ /正则/ {print ...}'` 按列过滤

### 2.2 `sed`：替换、删除、截取

```bash
sed -n '100,200p' app.log                    # 打印 100-200 行
sed -n '/O-20261029-001/,/O-20261029-002/p' app.log   # 打印两个标记之间的内容
sed 's/127.0.0.1/10.0.0.5/g' config.conf     # 预览替换（不写回）
sed -i 's/127.0.0.1/10.0.0.5/g' config.conf  # 原地替换（-i）
sed -i.bak 's/old/new/g' file                # 原地替换并留备份（推荐）
sed '/^#/d; /^$/d' config.conf               # 删掉注释行和空行
```

**纪律**：`sed -i` 前先不加 `-i` 跑一遍看输出，或者用 `-i.bak` 留备份。**在测试服务器上改配置文件，改错了服务起不来，比不改更麻烦。**

### 2.3 组合拳：一个订单号的完整链路

```bash
# 1. 找到这个订单所有日志
grep "O-20261029-001" app.log > /tmp/order.log

# 2. 看时间线（按时间排序后看首尾，能算出全链路耗时）
head -1 /tmp/order.log; tail -1 /tmp/order.log

# 3. 只看 ERROR/WARN 级别
grep -E "ERROR|WARN" /tmp/order.log

# 4. 统计每一步出现的次数（看有没有重复调用）
awk '{print $5}' /tmp/order.log | sort | uniq -c
```

---

## 3. 进程与资源：`ps top df du free`

### 3.1 `ps`：进程还在不在

```bash
ps aux | grep myservice           # 最常用（包含自己这条 grep，用下面两种避免）
ps -ef | grep "[m]yservice"       # 方括号技巧：排除 grep 自己
pgrep -af myservice               # 更干净的写法
ps -eo pid,ppid,pcpu,pmem,etime,cmd --sort=-pcpu | head -10   # CPU 占用 Top 10
ps -eo pid,rss,cmd --sort=-rss | head -10                     # 内存占用 Top 10（RSS 单位 KB）
```

**`ps aux | grep xxx` 一个必知的细节**：结果里会包含 `grep xxx` 这条命令本身。用 `[m]yservice` 或 `pgrep` 规避，否则你会误判"服务起了两个进程"。

```bash
# 看某个进程启动多久了（判断是不是刚重启过 → 502 的原因）
ps -eo pid,lstart,etime,cmd | grep "[m]yservice"
```

### 3.2 `top`：谁在吃 CPU

```bash
top -c          # 显示完整命令
top -H -p 1234  # 看这个进程内的各个线程（定位是哪个线程在飙 CPU）
```

`top` 顶部要会看三行：

| 指标 | 含义 | 异常判断 |
| --- | --- | --- |
| `load average: 0.5, 1.2, 2.0` | 1/5/15 分钟的平均负载 | **超过 CPU 核数**就是排队（`nproc` 看核数） |
| `%Cpu(s): 20 us, 30 sy, 50 id, 0 wa` | 用户态/内核态/空闲/等 IO | `sy` 高 → 系统调用多（上下文切换/中断）；`wa` 高 → 磁盘慢 |
| `KiB Mem / KiB Swap` | 内存和交换分区 | swap 被大量使用 → 内存不够，性能会崩 |

### 3.3 `df` / `du`：磁盘

```bash
df -h          # 各分区使用率（看还剩多少）
df -i          # inode 使用率 ← 关键：还有空间但写不进文件，就是 inode 满了
du -sh /opt/app/logs/*        # 每个子目录/文件占多大
du -sh * | sort -rh | head    # 当前目录下最大的 10 个
```

**两个经典故障**：

| 现象 | 命令 | 结论 |
| --- | --- | --- |
| `No space left on device` 但 `df -h` 显示还有空间 | `df -i` | **inode 耗尽**（海量小文件，日志碎片） |
| 服务跑着跑着写不了日志 | `du -sh` 找大文件 | 日志没切割，把磁盘吃满 |

### 3.4 `free`：内存

```bash
free -h
#               total        used        free      shared  buff/cache   available
# Mem:            15Gi       9.0Gi       1.0Gi       100Mi       5.0Gi       5.8Gi
```

**看 `available`，不要看 `free`**。Linux 会把空闲内存拿去做缓存（`buff/cache`），`free` 小是正常的；`available` 才是"新程序还能用多少"。

**判断内存泄漏**：`available` 持续下降、`swap` 持续上涨、进程 `RSS` 单调上涨不回落。

---

## 4. 网络排查：`curl` / `ss` / `ping`

### 4.1 `curl`：不只用来发请求

```bash
curl -v https://api.test.example.com/api/ping        # 看 DNS、TCP 连接、TLS、请求响应全过程
curl -o /dev/null -s -w "code=%{http_code} time=%{time_total}s\n" https://api.test.example.com/api/ping
curl -I https://api.test.example.com                 # 只看响应头
curl -X POST -H "Content-Type: application/json" -d '{"a":1}' https://api.test.example.com/api/order
curl --resolve api.test.example.com:443:10.0.0.5 https://api.test.example.com/api/ping   # 绕过 DNS 指定 IP（切环境神器）
curl -k https://self-signed.test/api                 # 忽略证书校验（仅测试环境）
curl --connect-timeout 3 --max-time 10 ...           # 连接超时 / 总超时
```

**`-w` 这个参数是测开必备**：一条命令直接拿到状态码和耗时，比看 `-v` 的一堆输出更实用，也容易做成脚本断言。

```bash
# 连续探活 10 次，看接口是否稳定（偶发 5xx 时用）
for i in $(seq 1 10); do
  curl -o /dev/null -s -w "%{http_code} %{time_total}\n" https://api.test.example.com/api/ping
done
```

### 4.2 `ss`（替代 netstat）：端口和连接状态

```bash
ss -tlnp                  # 监听中的 TCP 端口 + 对应进程（-p 要 root）
ss -tanp                  # 所有 TCP 连接
ss -s                     # 连接状态汇总（总数、TIME_WAIT 数）
ss -tan state time-wait | wc -l        # TIME_WAIT 数量
ss -tan state close-wait | wc -l       # CLOSE_WAIT 数量
ss -tan dst :3306          # 到 MySQL 的连接
```

```bash
# 端口被谁占了（服务起不来时第一个查的）
ss -tlnp | grep 8080
# 或
lsof -i :8080
```

**判断标准**（和网络篇呼应）：

- `TIME_WAIT` 多 → 连接没复用（客户端）或服务端主动关（服务端）。
- **`CLOSE_WAIT` 多 → 应用层没调 close，是代码 bug（连接泄漏）。**

### 4.3 `ping`

```bash
ping -c 4 api.test.example.com      # 只发 4 个包
ping -c 4 10.0.0.5
```

`ping` 通只能证明**网络层**通，**不代表服务可用**（端口可能没开、服务可能挂了）。真正的探活是 `curl` 或 `nc`。这是很常见的误判：运维说"ping 得通啊"，但服务根本没起。

---

## 5. 权限：`chmod` / `chown`

```bash
ls -l app.sh
# -rwxr-xr-x 1 qa qa 1200 Oct 29 10:00 app.sh
#  ↑权限      ↑属主 ↑属组
```

`rwx` 三组，分别对应**属主（u）/ 属组（g）/ 其他人（o）**：

| 数字 | 权限 | 含义 |
| --- | --- | --- |
| 7 | rwx | 读写执行 |
| 6 | rw- | 读写 |
| 5 | r-x | 读执行 |
| 4 | r-- | 只读 |
| 0 | --- | 无 |

```bash
chmod +x run_tests.sh          # 加执行权限（脚本跑不起来最常见的原因）
chmod 755 run_tests.sh         # rwxr-xr-x：脚本的标准权限
chmod 644 config.yaml          # rw-r--r--：配置文件的权限（不能有 x）
chmod -R 755 /opt/app/bin      # 递归
chown -R qa:qa /opt/app/logs   # 改属主和属组（容器里的挂载目录权限不对时必用）
```

**两个真实场景**：

1. 脚本从 Windows 拷到 Linux，`chmod +x` 忘了加 → `Permission denied`。
2. 容器挂载宿主机目录，容器内用户 UID 和宿主机不一致 → 写不进去 → `chown -R` 或 Dockerfile 里指定 UID。

---

## 6. 自查 Q4 完整作答

### Q4. `tail -f`、`grep -C 5`、`ps aux | grep xxx` 分别在什么排障场景用？

**`tail -f`：实时跟日志，看"现在正在发生什么"。**

> 场景：测试时接口报错，我一边复现一边展示服务器上的日志滚动，看请求进来那一刻服务端打了什么。
> 关键点：日志有轮转时必须用 `tail -F`（跟文件名而不是文件描述符），否则跨 0 点或文件被重建后就停止输出。
> 配合：`tail -F app.log | grep -v healthcheck` 过滤掉探活噪音；`tail -F app.log | grep -E "ERROR|Exception"` 只看异常。

**`grep -C 5`：定位到某一行后，看它前后的上下文。**

> 场景：日志里 grep 到 `order_no=O-20261029-001` 的 error 行，但我需要知道它前面请求带的是什么参数、后面抛的什么堆栈。`-C 5` 前后各看 5 行就够。
> 变体：看堆栈用 `-A`（后），看入参用 `-B`（前）。
> 为什么重要：只 grep 不带上下文，你只知道"报错了"，不知道"为什么报错"，等于没查到。

**`ps aux | grep xxx`：确认进程在不在、起了几个、什么时候起的。**

> 场景：接口全挂，先确认服务进程还活着；或者 `ss` 发现端口不对，确认是不是有多个实例抢端口。
> 技巧：用 `ps -ef | grep "[m]yservice"` 或 `pgrep -af myservice` 排除 grep 自己那条，否则会误判成两个进程。
> 加分：`ps -eo pid,lstart,etime,cmd | grep "[m]yservice"` 看启动时间，能判断"是不是刚重启过"——这对偶发 502 的排查很关键（重启期间请求会失败）。

**一句话串联**：

> 三者的关系是"先发现 → 再定位 → 最后确认状态"：`tail -f` 发现异常实时出现，`grep -C 5` 把异常周围的上下文拉出来定位原因，`ps aux` 确认服务本身还活着还是已经挂了。**排障时我一般三个窗口同时开着。**

---

## 7. 动手清单

- [ ] 用 `awk` 统计一次 access.log 的状态码分布，找出 5xx 占比。
- [ ] 用一个订单号跑一次完整链路：`grep` → `-C 10` → `awk` 统计步骤。
- [ ] `ss -tan state close-wait | wc -l`，看你们服务有没有连接泄漏。
- [ ] `df -i` 看一眼 inode 使用率，很多环境这里是隐性炸弹。
