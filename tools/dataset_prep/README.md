# 失物招领系统 — 数据集准备 + 训练 + 评估 脚本管线

基于 YOLOv8 的校园失物招领智能匹配系统：数据集准备、训练、评估全套脚本。
所有文件路径均位于 **E 盘**（C 盘零写入）。统一 **11 类**标签，单一事实来源为
`label_map.yaml`。

## 目录结构

```
tools/dataset_prep/
├── label_map.yaml          # 11 类定义 + 各源映射（单一事实来源）
├── common.py               # 共享工具（读取 label_map / 校验 / 写 YOLO txt）
├── convert_coco.py         # COCO 2017 -> 统一 11 类 YOLO
├── convert_leftincar.py    # leftincar-data -> 统一 11 类 YOLO（bmp->jpg，8:2 切分）
├── convert_homeobjects.py  # homeobjects-3K -> 仅 laptop
├── merge_and_split.py      # 三源合并 + 分层抽样 7:2:1
├── train_yolov8.py         # Ultralytics 训练
├── extract_metrics.py      # 结果 -> 论文 Table 4-x 表格（md + csv）
└── README.md
```

## 统一 11 类（索引固定）

```
0 phone   1 wallet  2 keys   3 backpack  4 suitcase  5 laptop
6 campus_card  7 glasses  8 notebook  9 umbrella  10 bottle
```

| 源 | 贡献的目标类 |
|---|---|
| COCO 2017 | phone, backpack(+handbag), suitcase, laptop, notebook(book), umbrella, bottle |
| leftincar | phone, wallet, keys, backpack, suitcase, laptop, campus_card, glasses |
| homeobjects | laptop |
| 视觉低置信降级 | 玩偶等未纳入训练类目的物品归“其他”类（论文需说明） |

## 环境

- Python venv：`E:\xuexixiangguan\pythonProject\gongcheng\失物招领系统\.venv\Scripts\python.exe`
- 依赖（已装）：pyyaml, Pillow, ultralytics
- 若缺失：`E:\...\失物招领系统\.venv\Scripts\python.exe -m pip install pyyaml pillow ultralytics`

## 运行顺序

```bash
# 0) 进入脚本目录（用项目 venv）
cd /e/xuexixiangguan/pythonProject/gongcheng/失物招领系统/tools/dataset_prep
PY=E:/xuexixiangguan/pythonProject/gongcheng/失物招领系统/.venv/Scripts/python.exe

# 1) 转换三源（全量，输出到 E:/mod/processed/...）
$PY convert_coco.py
$PY convert_leftincar.py
$PY convert_homeobjects.py

# 2) 合并 + 分层抽样 7:2:1 -> E:/mod/processed/final/{images,labels}/{train,val,test}
$PY merge_and_split.py

# 3) 训练（自有 GPU 机器，耗时较长）
$PY train_yolov8.py                 # yolov8n.pt
# $PY train_yolov8.py --model yolov8s.pt --batch 16   # 更大模型 / 更小 batch

# 4) 评估并生成论文表格
$PY extract_metrics.py              # 读 runs/detect/lostfound_v1/results.csv
```

## Smoke test（快速验证逻辑，不跑全量训练）

```bash
# 每个 convert 仅处理前 20 张：
$PY convert_coco.py --limit 20
$PY convert_leftincar.py --limit 20
$PY convert_homeobjects.py --limit 20

# 合并（基于上面小规模输出）：
$PY merge_and_split.py

# 训练脚本仅做语法检查：
$PY -c "import ast; ast.parse(open('train_yolov8.py').read())"

# 用一份假 results.csv 验证表格输出格式：
$PY extract_metrics.py --results fake_results.csv --per-class fake_per_class_ap.csv --out .
```

## 输出位置

- 处理后数据：`E:\mod\processed\`（`coco_*` / `leftincar/` / `homeobjects_laptop/` / `final/`）
- 训练结果：`runs/detect/lostfound_v1/`（相对脚本目录，位于 E 盘）
- 论文表格：`runs/detect/lostfound_v1/table_4x_metrics.{md,csv}` 或 `--out` 指定目录

## 关键说明

- **玩偶(doll)** 已移除训练类目：三源均无样本、毛绒材质难以识别；识别时低置信（< YOLO_CONF_THRESHOLD）统一归为“其他”类。
- **leftincar** 源图片为 bmp（约 18GB），convert 时转成 jpg（quality=95）省空间。
- **COCO** 图片目录可能嵌套一层 `train2017/train2017/`，脚本已自动兼容。
- 所有 `class_id` 已按 `label_map.yaml` 改写；YOLO 标注为
  `class_id cx cy w h`，坐标归一化到 `[0,1]`。
