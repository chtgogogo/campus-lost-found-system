# -*- coding: utf-8 -*-
"""补查：分节与页眉引用关系 / 附录段 / 公式形态 / 表头行识别。"""
import zipfile, re

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"


def ptext(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


z = zipfile.ZipFile(DOC)
xml = z.read("word/document.xml").decode("utf-8")
z.close()

print("=" * 84)
print("一、分节 (w:sectPr) 与页眉页脚引用")
print("=" * 84)
for i, s in enumerate(re.findall(r"<w:sectPr.*?</w:sectPr>", xml, re.S)):
    hr = re.search(r'<w:headerReference[^>]*w:type="(\w+)"[^>]*r:id="([^"]+)"', s)
    fr = re.search(r'<w:footerReference[^>]*w:type="(\w+)"[^>]*r:id="([^"]+)"', s)
    tp = re.search(r'<w:type w:val="(\w+)"', s)
    print("  sect%-2d type=%-10s header=%s footer=%s" % (
        i, tp.group(1) if tp else "(default)",
        (hr.group(1) if hr else "-"), (fr.group(1) if fr else "-")))

print("\n" + "=" * 84)
print("二、附录段 / 致谢段 (582-590)")
print("=" * 84)
parts = re.split(r"(<w:tbl>.*?</w:tbl>)", xml, flags=re.S)
gi = 0
for part in parts:
    if part.startswith("<w:tbl>"):
        gi += len(re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S))
        continue
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        if 578 <= gi <= 589:
            t = ptext(p).strip()
            s = re.search(r"<w:pPr>(.*?)</w:pPr>", p, re.S)
            sid = re.search(r'<w:pStyle w:val="([^"]+)"', p)
            sz = re.findall(r'<w:sz w:val="(\d+)"', p)
            fnt = re.findall(r'w:eastAsia="([^"]+)"', p)
            print("  [%4d] style=%-9s sz=%s ea=%s | %s" % (
                gi, sid.group(1) if sid else "-", sorted({int(x) / 2 for x in sz}),
                sorted(set(fnt)), t[:46].replace("\n", " ")))
        gi += 1

print("\n" + "=" * 84)
print("三、公式相关表述（正文含 '式' / '公式' 的段落）")
print("=" * 84)
gi = 0
for part in parts:
    if part.startswith("<w:tbl>"):
        gi += len(re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S))
        continue
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        t = ptext(p)
        if ("公式" in t or re.search(r"式\s*[（(]?\s*\d+\s*[-.．]", t)) and len(t.strip()) > 4:
            print("  [%4d] %s" % (gi, t[:76].replace("\n", " ")))
        gi += 1

print("\n" + "=" * 84)
print("四、表格首行(表头)识别 —— 每个表的第一行文本")
print("=" * 84)
for ti, tbl in enumerate(re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)):
    rows = re.findall(r"<w:tr[ >].*?</w:tr>", tbl, re.S)
    if not rows:
        continue
    hdr = " | ".join(ptext(c)[:14] for c in re.findall(r"<w:tc>.*?</w:tc>", rows[0], re.S))
    ncol = len(re.findall(r"<w:tc>", rows[0]))
    print("  表%-2d 行数=%d 列数=%d 首行: %s" % (ti + 1, len(rows), ncol, hdr[:90]))
