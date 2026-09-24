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
