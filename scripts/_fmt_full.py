# -*- coding: utf-8 -*-
"""全维度格式体检：图注/表注/参考文献上标/公式/页眉页脚/目录/标题/摘要区。"""
import zipfile, re

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"

z = zipfile.ZipFile(DOC)
names = z.namelist()
xml = z.read("word/document.xml").decode("utf-8")
hdrs = {n: z.read(n).decode("utf-8") for n in names if re.match(r"word/(header|footer)\d*\.xml", n)}
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
        b = "<w:b/>" in r or re.search(r"<w:b [^>]*/>", r) is not None
        sup = 'w:vertAlign w:val="superscript"' in r
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
        out.append(dict(t=t, ea=ea, af=af, sz=sz, b=b, sup=sup))
    return out


seq = []
gi = 0
for part in parts:
    is_tbl = part.startswith("<w:tbl>")
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        seq.append((gi, p, is_tbl))
        gi += 1

print("总段落(含表格内):", len(seq), " | 表格数:", xml.count("<w:tbl>"), " | 图片数:", xml.count("<w:drawing>"))

print("\n" + "=" * 84)
print("一、图注 / 表注（批注[57]：图注在图片下方，黑体五号居中）")
print("=" * 84)
for i, p, it in seq:
    t = ptext(p).strip()
    if re.match(r"^图\s*\d+[\.\-]", t) or re.match(r"^表\s*\d+[\.\-]", t):
        rs = runs(p)
        s = ppr(p)
        jc = re.search(r'<w:jc w:val="(\w+)"', s)
        ln = re.search(r'<w:spacing[^>]*?w:line="(\d+)"[^>]*?(?:w:lineRule="(\w+)")?', s)
        print("  [%4d]%s %-34s fonts=%s sz=%s b=%s jc=%s line=%s" % (
            i, " TBL" if it else "    ", t[:34],
            sorted({(x["ea"] or "-", x["af"] or "-") for x in rs})[:2],
            sorted({x["sz"] for x in rs}), sorted({x["b"] for x in rs}),
            jc.group(1) if jc else "-", ln.group(0)[:32] if ln else "-"))

print("\n" + "=" * 84)
print("二、参考文献上标（批注[21][34]：正文引用 [n] 应上标）")
print("=" * 84)
nosup, hassup = [], []
for i, p, it in seq:
    if it:
        continue
    rs = runs(p)
    for x in rs:
        if re.fullmatch(r"\[[\d,\s\-–—]+\]", x["t"].strip()):
            (hassup if x["sup"] else nosup).append((i, x["t"].strip(), ptext(p)[:30]))
print("  已上标: %d 处   未上标: %d 处" % (len(hassup), len(nosup)))
for i, t, c in nosup[:25]:
    print("    [%4d] %-8s 上下文: %s" % (i, t, c.replace("\n", " ")))

print("\n" + "=" * 84)
print("三、公式（批注[102]：TNR 小四、固定值40磅、居中、编号靠右）")
print("=" * 84)
print("  OMML 公式数:", xml.count("<m:oMath"))
print("  含公式编号 式( :", len(re.findall(r"式\s*[（(]\s*\d", ptext(xml))))
for i, p, it in seq:
    if "<m:oMath" in p:
        s = ppr(p)
        jc = re.search(r'<w:jc w:val="(\w+)"', s)
        ln = re.search(r'<w:spacing[^>]*?w:line="(\d+)"[^>]*?(?:w:lineRule="(\w+)")?', s)
        rs = runs(p)
        print("    [%4d] jc=%s line=%s texts=%s" % (
            i, jc.group(1) if jc else "-", ln.group(0)[:34] if ln else "-",
            [x["t"][:18] for x in runs(p)][:3]))

print("\n" + "=" * 84)
print("四、页眉页脚（批注[2]）")
print("=" * 84)
for n, h in hdrs.items():
    txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", h, re.S))
    jc = re.search(r'<w:jc w:val="(\w+)"', h)
    szs = sorted({int(m) / 2.0 for m in re.findall(r'<w:sz w:val="(\d+)"', h)})
    fonts = sorted(set(re.findall(r'w:eastAsia="([^"]+)"', h)))
    print("  %-22s 文字=%r" % (n.split("/")[-1], txt[:46]))
    print("      jc=%s sz=%s eastAsia=%s  页码域=%s" % (
        jc.group(1) if jc else "-", szs, fonts, "PAGE" in h))

print("\n" + "=" * 84)
print("五、目录区（TOC 域）")
print("=" * 84)
print("  TOC 域数量:", xml.count("TOC \\"), "| 目录条目样式:",
      sorted(set(re.findall(r'<w:pStyle w:val="([^"]+)"', xml)))[:0] or "-")

print("\n" + "=" * 84)
print("六、各级标题实际格式（批注[14]）")
print("=" * 84)
heads = [(i, p) for i, p, it in seq if not it and psid(p) in ("000047", "000049", "00004b")]
print("  标题段落数: %d (h1/h2/h3=%d/%d/%d)" % (
    len(heads), sum(1 for _, p in heads if psid(p) == "000047"),
    sum(1 for _, p in heads if psid(p) == "000049"),
    sum(1 for _, p in heads if psid(p) == "00004b")))
from collections import Counter
for sid, label in (("000047", "一级"), ("000049", "二级"), ("00004b", "三级")):
    sub = [(i, p) for i, p in heads if psid(p) == sid]
    cc = Counter()
    for i, p in sub:
        rs = runs(p)
        key = (tuple(sorted({(x["ea"] or "-", x["af"] or "-") for x in rs})),
               tuple(sorted({x["sz"] for x in rs})))
        cc[key] += 1
    print("  %s(%s) n=%d 显式格式分布:" % (label, sid, len(sub)))
    for k, v in cc.most_common(4):
        print("      x%-3d fonts=%s sz=%s" % (v, k[0][:2], k[1]))
    if sub:
        i, p = sub[0]
        print("      样例[%d]: %r  pPr=%s" % (i, ptext(p)[:30], ppr(p)[:150]))

print("\n" + "=" * 84)
print("七、中文摘要区对齐/缩进/加粗（批注[5][6]）")
print("=" * 84)
for i, p, it in seq:
    if 19 <= i <= 28:
        s = ppr(p)
        jc = re.search(r'<w:jc w:val="(\w+)"', s)
        flc = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', s)
        fl = re.search(r'<w:ind[^>]*?w:firstLine="(-?\d+)"', s)
        ln = re.search(r"<w:spacing[^>]*/>", s)
        rs = runs(p)
        print("  [%2d] %-26s jc=%s flc=%s firstLine=%s b=%s" % (
            i, ptext(p)[:26].replace("\n", " "), jc.group(1) if jc else "-",
            flc.group(1) if flc else "-", fl.group(1) if fl else "-",
            sorted({x["b"] for x in rs})))
        print("       spacing=%s" % (ln.group(0)[:110] if ln else "-"))
