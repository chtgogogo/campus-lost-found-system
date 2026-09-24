# 压测脚手架（v17 任务②）

locust 4 场景压测：物品列表 / 发布（含同步 YOLO 识别）/ 匹配列表 / 交接码验证（错码路径）。
单机校园项目，诚实口径：单 uvicorn 进程、本机回环、关闭限流与 Redis（内存兜底）。

## 一次性准备

```bash
# 1) 安装压测依赖（独立于主 requirements.txt，CI 不装）
.venv/Scripts/python.exe -m pip install -r evaluation/loadtest/requirements.txt

# 2) MySQL 对比时才需要：本机 Docker 起 MySQL 8（端口 3307 避让本机 3306）
docker run -d --name loadtest-mysql -e MYSQL_ROOT_PASSWORD=loadtest -e MYSQL_DATABASE=loadtest -p 3307:3306 mysql:8.0
```

## 跑一个数据点（播种 → 起服务 → 压测 → 收数 → 停服务，全自动）

```bash
# 场景: list | publish | matches | handover | mixed（混合读写，WAL 对比的关键场景）
# 库: sqlite | mysql
.venv/Scripts/python.exe evaluation/loadtest/run_one.py --scenario publish --db sqlite --label sqlite_baseline -u 10 -r 5 -t 60
```

输出：
- `evaluation/loadtest/_results/<label>_<scenario>_stats.csv`（locust 明细）
- `evaluation/loadtest/_results/<label>_<scenario>.summary.txt`（QPS/p95/错误率/锁错误数）
- `evaluation/loadtest/_env/server_<label>.log`（服务端日志，锁错误统计源）

## 口径与红线（数字表引用时必须带上）

1. **发布场景含同步 YOLO 识别**（v17④ 改异步前的真实形态）；每次上传同一 64px PNG，YOLO 以 640 输入真实推理。
2. **交接码验证为错码路径**：码行行锁查询 + 恒时比较 + attempts 写提交；业务 4xx（码错）视为预期成功，仅 5xx 计失败。正确码路径一次性流转（验证即置位），不可重复压测。错满 5 次锁定，种子 1 万条匹配 → 5 万次错误尝试内路径不变。
3. 关闭限流（RATE_LIMIT_ENABLED=false）与 Redis（内存兜底）；JWT 每次随机；**压测库独立**（`_env/loadtest.db` / MySQL `loadtest` schema），绝不碰 dev.db。
4. 每次 run_one 全量重置播种（drop_all + create_all + 种子），配置间数据状态一致，可横向对比。
5. 「database is locked」计数来自服务端日志（uvicorn log-level=warning 下 SQLAlchemy 异常仍会落到 traceback）。

## 种子规模（seed_loadtest.py）

| 用户 | 失物 | 拾物 | 匹配 | 用途 |
|---|---|---|---|---|
| loadtest_list | 200（书包/待匹配） | 200 | 2000（10/失物，待认领） | list / matches 场景 |
| loadtest_hand | 100 | 100 | 10000（全配对，认领中+有效码行 1111/2222） | handover 场景 |

发布场景运行期还会新增拾物与候选匹配（每发布 ≤50 条候选），属被测系统真实写放大，各配置一致。
