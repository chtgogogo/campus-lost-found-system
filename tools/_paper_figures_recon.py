import os, re
from docx import Document
from docx.oxml.ns import qn

DOCX = r"D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文-2026版（7-6）.docx"
OUT = r"E:/xuexixiangguan/pythonProject/gongcheng/失物招领系统/tools/_paper_figures_out"
os.makedirs(OUT, exist_ok=True)

doc = Document(DOCX)
body = doc.element.body

# 1. 导出所有图片
relid_to_file = {}
img_idx = 0
for rel in doc.part.rels.values():
    if "image" in rel.reltype:
        img_idx += 1
        blob = rel.target_part.blob
        if blob[:4] == b'\x89PNG':
            ext = 'png'
        elif blob[:2] == b'\xff\xd8':
            ext = 'jpg'
        elif blob[:4] == b'\x01\x00\x00\x00':
            ext = 'emf'
        elif blob[:2] == b'\xd7\xcd':
            ext = 'wmf'
        else:
            ext = 'bin'
        fname = f"fig_{img_idx:02d}.{ext}"
        with open(os.path.join(OUT, fname), 'wb') as f:
            f.write(blob)
        relid_to_file[rel.rId] = (fname, len(blob))

# 2. 定位图所在段落 + 最近标题
para_elems = list(body.findall(qn('w:p')))
para_texts = [p.text for p in para_elems]


def recent_heading(idx):
    for j in range(idx, -1, -1):
        p = para_elems[j]
        pPr = p.find(qn('w:pPr'))
        if pPr is not None:
            style = pPr.find(qn('w:pStyle'))
            if style is not None:
                val = style.get(qn('w:val'))
                if val and 'Heading' in val:
                    return f"[{val}] {para_texts[j][:40]}"
    return "(无标题)"


located = []
for i, p in enumerate(para_elems):
    embeds = [blip.get(qn('r:embed')) for blip in p.iter(qn('a:blip'))]
    if embeds:
        located.append((i, embeds))

print(f"== 共导出图片 {img_idx} 张，位于 {len(located)} 个段落 ==")
for i, embeds in located:
    figs = [relid_to_file.get(r, (r, 0))[0] for r in embeds]
    print(f"\n段落[{i}] 标题上下文: {recent_heading(i)}")
    print(f"  段落文本: {para_texts[i][:60]!r}")
    print(f"  图片: {figs}")

# 3. 搜索 mermaid / 文本图关键字
print("\n== 文本图关键字搜索 ==")
hits = 0
for i, t in enumerate(para_texts):
    if re.search(r'mermaid|sequenceDiagram|graph\s+(TD|LR)|flowchart|@startuml|```', t):
        print(f"  段[{i}]: {t[:80]!r}")
        hits += 1
if hits == 0:
    print("  (无 mermaid/代码块类文本图)")

# 4. 搜索图说/标题关键字（图X / 图 X / Figure）
print("\n== 图说/图标题搜索 ==")
for i, t in enumerate(para_texts):
    if re.search(r'图\s*\d+|Figure\s*\d+|架构图|流程图|时序图|用例图|类图|部署图|E-R|ER图', t):
        print(f"  段[{i}] {t[:60]!r}")
