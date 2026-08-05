"""Fill thesis table[2] (mAP results) with 12-class metrics from v12_val_metrics.json.

Adds an '其他类' column to the existing 4-column table
(指标 | COCO通用类 | 校园专属类 | 整体) so it becomes 5 columns.
Also rewrites the first 4 columns with 12-class group metrics
(COCO/校园/整体 are recomputed on the 12-class model).
"""
import os
import shutil
import json
import docx
from docx.shared import Inches

OUT = "v12_val_metrics.json"
THESIS = r'D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文-2026版（7-6）.docx'
BAK = THESIS + ".bak.20260724v12"

d = json.load(open(OUT, encoding="utf-8"))

if not os.path.exists(BAK):
    shutil.copy(THESIS, BAK)
    print("backup ->", BAK)

doc = docx.Document(THESIS)
t = doc.tables[2]

# add a new column (其他类) if currently 4 cols
if len(t.columns) == 4:
    new_col = t.add_column(Inches(0.9))
    cells = new_col.cells
    cells[0].text = "其他类"
    cells[1].text = "%.3f" % d["other_map50"]
    cells[2].text = "%.3f" % d["other_map50_95"]
    cells[3].text = "图4-4"

# header already: 指标 | COCO通用类 | 校园专属类 | 整体 | 其他类
r1 = t.rows[1].cells  # mAP@0.5
r2 = t.rows[2].cells  # mAP@0.5:0.95

r1[1].text = "%.3f" % d["coco_map50"]
r1[2].text = "%.3f" % d["campus_map50"]
r1[3].text = "%.3f" % d["map50"]
r2[1].text = "%.3f" % d["coco_map50_95"]
r2[2].text = "%.3f" % d["campus_map50_95"]
r2[3].text = "%.3f" % d["map50_95"]

try:
    doc.save(THESIS)
    print("table[2] updated in original thesis file")
except PermissionError:
    alt = THESIS.replace(".docx", "-12cls.docx")
    doc.save(alt)
    print("ORIGINAL LOCKED (Word open?) -> saved to:", alt)
    print("Close Word / release the file, then re-run this script to overwrite the original.")
print("  COCO   @0.5=%.3f  @0.5:0.95=%.3f" % (d["coco_map50"], d["coco_map50_95"]))
print("  CAMPUS @0.5=%.3f  @0.5:0.95=%.3f" % (d["campus_map50"], d["campus_map50_95"]))
print("  OTHER  @0.5=%.3f  @0.5:0.95=%.3f" % (d["other_map50"], d["other_map50_95"]))
print("  OVERALL @0.5=%.3f  @0.5:0.95=%.3f" % (d["map50"], d["map50_95"]))
