import os, io
from PIL import Image
from docx import Document

NEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_paper_figures_new")
names = ["fig_03_use_case.png","fig_05_sequence.png","fig_07_state.png","fig_09_er.png",
         "fig_10_class.png","fig_11_deploy.png","fig_41_flow.png","fig_42_pseudocode.png"]

print("== 8 PNG 尺寸/模式 ==", flush=True)
for n in names:
    p = os.path.join(NEW, n)
    im = Image.open(p)
    print(f"  {n:26} {im.size} {im.mode} {os.path.getsize(p)}B", flush=True)

DOCX = r"D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文-2026版（7-6）.docx"
TARGETS = {"rId20":"fig_03_use_case.png","rId21":"fig_05_sequence.png","rId22":"fig_07_state.png",
 "rId23":"fig_11_deploy.png","rId24":"fig_10_class.png","rId27":"fig_05_sequence.png",
 "rId30":"fig_09_er.png","rId31":"fig_10_class.png","rId32":"fig_11_deploy.png",
 "rId28":"fig_41_flow.png","rId35":"fig_42_pseudocode.png"}

print("\n== docx blob vs 新 PNG 原始字节 ==", flush=True)
doc = Document(DOCX)
ok = 0
for rid, png in TARGETS.items():
    cb = bytes(doc.part.rels[rid].target_part.blob)
    raw = open(os.path.join(NEW, png), "rb").read()
    same = (cb == raw)
    ok += same
    print(f"  {rid:8} blob={len(cb):>8} raw={len(raw):>8} {'IDENTICAL' if same else '*** DIFF ***'}", flush=True)
print(f"\nTARGET 字节一致: {ok}/{len(TARGETS)}", flush=True)
