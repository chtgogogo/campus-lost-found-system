# 对外数字口径表（简历/面试唯一来源）

> 纪律：任何对外场合（简历/面试/README）**只说这张表里的数字**；每个数字必须能沿
> 「来源文件 → 复现命令」两步对账。改了代码先改这张表。
> 最后核对：2026-09-25（v17 工程化补强批次）。

---

## 一句话口径（简历项目描述建议）

> 基于 YOLOv8 的校园失物招领智能匹配系统：可解释的七维加权匹配引擎 + 三层评测集驱动的
> 迭代（主集 F1 62.9%→78.0%）+ 安全交接闭环（动态交接码/恒时比较/行锁/审计黑匣子）；
> 后端 FastAPI 411 条行为级测试 CI 门禁，前端 Vue3 + TS + vitest。

## 核心数字

| # | 数字 | 来源文件 | 复现命令 |
|---|---|---|---|
| 1 | 测试 **411 用例（409 通过 / 2 跳过 / 0 失败）** | `审查证据/pytest_full_after_batch2.txt` | `python -m pytest -q`（约 5 分钟，串行） |
| 2 | 主集 **F1 78.0%**（P76.2/R80.0，40 对，阈值 78） | `evaluation/results-v16.md` | `python evaluation/run_eval.py` |
| 3 | 控制集 **F1 93.6%**（30 条单维度敏感性，v16 主动 -1.9pp） | `evaluation/results-control-v16.md` | `python evaluation/run_eval.py --dataset dataset_control.json` |
| 4 | 盲集首跑 **F1 57.1%**（12 对冻结未调参；与主集差距=量化后的乐观偏差） | `evaluation/results-blind-20260924.md` | `python evaluation/run_eval.py --dataset dataset_blind.json` |
| 5 | 评测基线 **F1 62.9% → 78.0%**（v13→v16，每版留结果文件） | `evaluation/results-v13~v16.md` + git tag | `git checkout v13 && python evaluation/run_eval.py`（v16 同理） |
| 6 | 匹配列表 **165ms→18ms / 每请求 SQL 630→5 条**（300 匹配场景） | `审查证据/bench_before/after_20260924.txt` | `python scripts/bench_match_list.py` |
| 7 | 前端主 chunk **1249KB→582KB（gzip 406→195KB，-52%）** | `审查证据/web_build_after_element_ondemand.txt` | `cd web && npm run build` |
| 8 | 演示态死代码拆除 **约 -2860 行 / 5 文件** | git commit f6a8905 | `git show --stat f6a8905` |
| 9 | CI **双作业绿**：后端 ruff+407 passed；前端 vue-tsc+vitest 8 passed | `审查证据/ci_run_35953746464_batch2_green.txt` | GitHub Actions 页（run 35953746464 / 35954141816） |
| 10 | 安全专项：**JWT type 隔离 / 封禁闭环 / 交接码恒时比较+错5次锁定+行锁 / 审计黑匣子** | CHANGELOG v16 前后各条 + `tests/test_p1_hardening.py` 等 | `python -m pytest tests/test_auth.py tests/admin_tests/ -q` |
| 11 | 评测 CI 门禁阈值 **76**（主集 F1 78.0 − 2pp 容差；`--fail-under 99` 实测退出码 1 会挡） | `app/core/config.py`（EVAL_FAIL_UNDER）+ `审查证据/eval_gate_fail_under_99_block.txt` | `python evaluation/run_eval.py --fail-under 99; echo $?`（退出码 1=门禁生效） |
| 12 | 压测·开 WAL 前后（SQLite，10 用户/60s，`evaluation/loadtest/`）：匹配列表 **52.1→61.3 QPS（p95 180→130ms）**、发布（含同步识别）**5.4→6.8 QPS（p95 1800→1400ms）**、交接码验证 **79.8→90.8 QPS（p95 37→17ms）**、物品列表 90.2 持平（p95 17→13ms）；全场景 0 错误 0 锁错误 | `evaluation/loadtest/_results/sqlite_baseline_*.summary.txt` + `sqlite_wal_*.summary.txt` | `python evaluation/loadtest/run_one.py --scenario matches --db sqlite --label 对比标签 -u 10 -r 5 -t 60`（先 `-r requirements` 装 locust；口径见 `evaluation/loadtest/README.md`） |
| 13 | 压测·SQLite vs MySQL 8（同脚本同机 10 用户/60s）：MySQL 全面落后——列表 84.9 vs **90.2** QPS、匹配列表 42.6 vs **61.3**、发布 6.0 vs **6.8**、交接码 65.9 vs **90.8**（p95 180 vs **17ms**）、混合 22.9 vs **27.6**；主因=Docker 回环 TCP 每查询一次往返（匹配列表 5 条 SQL → 5 次 RTT）；两库全场景 0 错误 0 锁错误 | `evaluation/loadtest/_results/mysql_*.summary.txt` + `sqlite_wal_*.summary.txt` | 同上，`--db mysql`（MySQL 容器 `docker run` 命令见 loadtest README） |
| 14 | 发布接口异步化前后（同一压测口径 10 用户/60s）：**5.4 → 74.4 QPS（13.8 倍），p95 1800ms → 68ms（-96%），中位 1600ms → 25ms**；识别转后台任务表（同图全库只推理一次），压测实证任务/物品状态 100% 回填一致 | `evaluation/loadtest/_results/sqlite_baseline_publish.summary.txt`（改前）vs `sqlite_async_publish.summary.txt`（改后）+ `审查证据/pytest_v17_task4.txt` | `python evaluation/loadtest/run_one.py --scenario publish --db sqlite --label sqlite_async -u 10 -r 5 -t 60`（改前数字 checkout 提交 f7cc411 后同命令） |
| 15 | 可观测层（零外部依赖）：request_id 全链路 + JSON 日志 + `/metrics`（QPS/p95/错误率）+ 慢 SQL 告警（>100ms）；**演示实证**：同一条 request_id 把慢 SQL WARNING（166.3ms）与接口日志（319.2ms）串成一条线 | `app/core/observability.py` + `审查证据/obs_demo_evidence.txt` + `tests/test_observability.py` | `OBS_DEMO_ENDPOINT=true` 起服务 → `curl /__demo/slow` → `grep <rid> server.log`（README「可观测性」节有完整演示命令） |

## 必须带着限定语说的数字（主动交代，防追问）

- **78.0% 必须带「主集参与调参」**：下一步主动说"所以我们建了 12 对冻结盲集，首跑 57.1%，
  两者的差距正是乐观偏差的量化"——这是加分项，藏起来被挖出来是减分项（`docs/known-tradeoffs.md` A1）。
- **93.6% 不当主指标**：控制集是单维度敏感性验证（30 条自建），不是泛化成绩。
- **411 用例必须带「行为级断言 + CI 门禁」**：数字本身无意义，门禁才是工程含义。
- **18ms 必须带场景**：300 匹配 / 单机 SQLite / 10 轮均值；不是通用压测结论。
- **52% 包体削减必须带方法**：JS 按需引入（unplugin），CSS 仍全局（取舍见 trade-offs D1）。

## 已废弃/禁用的旧数字（在任何对外材料中出现即为错误）

| 禁用数字 | 原因 | 替代 |
|---|---|---|
| 控制集 95.5% | v15.2b 旧口径；v16 语义修正后为 93.6% | 93.6% |
| MATCH_THRESHOLD=80 | v16 重标定为 78 | 78 |
| 387/395/398/401/406/408 用例 | 历史版本口径，均已过期 | 411（409/2） |
| pytest "55 failed" | 2026-09-23 已定性为并发互删环境假象（CHANGELOG 有实测记录） | 引用最新绿跑 |
| F1 58.8%→62.9% 作为起点叙事可保留 | 属实（v12→v13），但无逐样本结果文件 | 可用，注明"早期口径，见 docs/prd/v13" |

## 版本锚点

`v13`(69ea6eb) `v14`(063de15) `v15`(1a4d65d) `v15.2b`(a829a98) `v16`(a732745) 已推 origin——
任一版本的评测数字可 `git checkout <tag>` 后用表内命令复现。
