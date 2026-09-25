# 验收基线（ACCEPTANCE.md 草稿，用户可改定；红线一旦写入，下次验收以此为准）

- 测试红线：全量 pytest 0 failed；主集评测 F1 >= 76（评测门禁阈值，config EVAL_FAIL_UNDER）
- 性能红线：发布接口 p95 < 500ms（异步化后基线 68ms）；run_eval < 30s
- 安全红线：JWT_SECRET 禁弱默认（启动校验）；SHOW_SMS_CODE 生产必须 false；DEMO_MODE 生产必须 false；盲集 dataset_blind.json 禁止进常规 CI
- 评测集：evaluation/dataset.json（40 对主集）；盲集 evaluation/dataset_blind.json（12 对，每大版本人工跑一次）
- 豁免项：pip-audit PYSEC-2026-3740（nltk 上游无修复版，本地词表场景无危害；修复发布后移除）
- 不做项：Redis 集群/分布式/LLM 结构化提取/向量检索（单机校园诚实规模，理由见 CHANGELOG v18⑨）
