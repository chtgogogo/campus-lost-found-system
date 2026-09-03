# -*- coding: utf-8 -*-
"""最终异常清单：找出所有显式设置且不符合模板基准的段落。"""
import zipfile, re
from collections import Counter

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"

z = zipfile.ZipFile(DOC)
xml = z.read("word/document.xml").decode("utf-8")
z.close()
parts = re.split(r"(<w:tbl>.*?</w:tbl>)", xml, flags=re.S)


def ptext(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


def psid(p):
    m = re.search(r'<w:pStyle w:val="([^"]+)"', p)
    return m.group(1) if m else None


def ppr(p):
    m = re.search(r"<w:pPr>(.*?)</w:pPr>", p, re.S)
    return m.group(1) if m else ""


def runs(p):
    out = []
    for r in re.findall(r"<w:r[ >].*?</w:r>", p, re.S):
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", r, re.S))
        if not t.strip():
            continue
        ea = af = None
        sz = None
        m = re.search(r"<w:rFonts[^>]*/>", r) or re.search(r"<w:rFonts[^>]*>.*?</w:rFonts>", r, re.S)
        if m:
            f = m.group(0)
            x = re.search(r'w:eastAsia="([^"]+)"', f)
            ea = x.group(1) if x else None
            x = re.search(r'w:ascii="([^"]+)"', f)
            af = x.group(1) if x else None
        m = re.search(r'<w:sz w:val="(\d+)"', r)
        if m:
            sz = int(m.group(1)) / 2.0
        out.append((t, ea or "-", af or "-", sz))
    return out


seq = []  # (idx, para, in_table, global_para_no)
gi = 0
for part in parts:
    is_tbl = part.startswith("<w:tbl>")
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        seq.append((gi, p, is_tbl))
        gi += 1

print("=" * 84)
print("一、表格内段落字号分布（批注[123]：表格5号宋体 = 10.5pt）")
print("=" * 84)
tc = Counter()
tbl_para = []
for i, p, it in seq:
    if it and ptext(p).strip():
        for x in runs(p):
            tc[x[3]] += 1
        tbl_para.append((i, p))
print("  表格内 run 字号分布:", tc.most_common())
bad9 = [(i, p) for i, p in tbl_para if any(x[3] == 9.0 for x in runs(p))]
print("  含 9pt 的表格段落数:", len(bad9))
for i, p in bad9[:10]:
    print("    [%4d] %-40s sz=%s fonts=%s" % (i, ptext(p)[:40].replace("\n", " "),
                                              sorted({x[3] for x in runs(p)}),
                                              sorted({(x[1], x[2]) for x in runs(p)})))

print("\n" + "=" * 84)
print("二、正文（表格外）显式行距 ≠ 400/exact 的段落（批注[18]：固定值20磅）")
print("=" * 84)
for i, p, it in seq:
    if it or not ptext(p).strip():
        continue
    s = ppr(p)
    m = re.search(r'<w:spacing[^>]*?w:line="(\d+)"', s)
    r = re.search(r'<w:spacing[^>]*?w:lineRule="(\w+)"', s)
    if m:
        val, rule = m.group(1), (r.group(1) if r else "auto")
        if not (val == "400" and rule == "exact"):
            print("  [%4d] line=%s/%s  %s" % (i, val, rule, ptext(p)[:46].replace("\n", " ")))

print("\n" + "=" * 84)
print("三、正文（表格外）显式字号 ≠ 12pt 且非封面/目录区(前80段)的段落")
print("=" * 84)
for i, p, it in seq:
    if it or not ptext(p).strip() or i < 80:
        continue
    rs = runs(p)
    if not rs:
        continue
    szs = {x[3] for x in rs if x[3] is not None}
    if szs and not szs <= {12.0}:
        t = ptext(p).strip()
        if re.match(r"^图\s*\d+", t) or re.match(r"^表\s*\d+", t):
            continue
        print("  [%4d] sz=%s fonts=%s | %s" % (i, sorted(szs),
                                               sorted({(x[1], x[2]) for x in rs})[:2],
                                               t[:44].replace("\n", " ")))

print("\n" + "=" * 84)
print("四、摘要区（20-28）详细格式")
print("=" * 84)
for i, p, it in seq:
    if 19 <= i <= 28 and ptext(p).strip():
        rs = runs(p)
        s = ppr(p)
        line = re.search(r'<w:spacing[^>]*?w:line="(\d+)"[^>]*?(?:w:lineRule="(\w+)")?', s)
        flc = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', s)
        print("  [%2d] %-30s fonts=%s sz=%s line=%s flc=%s" % (
            i, ptext(p)[:30].replace("\n", " "),
            sorted({(x[1], x[2]) for x in rs})[:2], sorted({x[3] for x in rs}),
            line.group(0)[:34] if line else "-", flc.group(1) if flc else "-"))
