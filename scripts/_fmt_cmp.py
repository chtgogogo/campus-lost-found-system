# -*- coding: utf-8 -*-
"""核对：批注原文 + 模板摘要区/页眉实测 + 论文公式形态 + 异常一级标题。"""
import zipfile, re

TMPL = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\参考模板拿来填\计算机学院毕业论文（设计）论文模板-应用开发型（人工智能、智能科学与技术专业适用）-2026版（7-6）.docx"
DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"


def ptext(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


def ppr(p):
    m = re.search(r"<w:pPr>(.*?)</w:pPr>", p, re.S)
    return m.group(1) if m else ""


def runs(p):
    out = []
    for r in re.findall(r"<w:r[ >].*?</w:r>", p, re.S):
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", r, re.S))
        ea = af = None
        sz = None
        b = "<w:b/>" in r
        m = re.search(r"<w:rFonts[^>]*/>", r) or re.search(r"<w:rFonts[^>]*>.*?</w:rFonts>", r, re.S)
        if m:
            x = re.search(r'w:eastAsia="([^"]+)"', m.group(0))
            ea = x.group(1) if x else None
            x = re.search(r'w:ascii="([^"]+)"', m.group(0))
            af = x.group(1) if x else None
        m = re.search(r'<w:sz w:val="(\d+)"', r)
        if m:
            sz = int(m.group(1)) / 2.0
        out.append(dict(t=t, ea=ea, af=af, sz=sz, b=b))
    return out


print("=" * 84)
print("一、模板批注原文（含页眉/公式/表格/图 相关）")
print("=" * 84)
z = zipfile.ZipFile(TMPL)
cx = z.read("word/comments.xml").decode("utf-8")
z.close()
for c in re.findall(r"<w:comment .*?</w:comment>|<w:comment>.*?</w:comment>", cx, re.S):
    cid = re.search(r'w:id="(\d+)"', c)
    txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", c, re.S)).strip()
    # 只打印与格式相关的关键批注
    if any(k in txt for k in ("页眉", "页码", "公式", "楷体", "宋体", "黑体", "Times", "磅", "上标", "居中", "图", "表")):
        print("  [%s] %s" % (cid.group(1) if cid else "?", txt.replace("\n", " ")[:180]))

print("\n" + "=" * 84)
print("二、模板 摘要区（20-28）实测格式 —— 论文应对齐此值")
print("=" * 84)
z = zipfile.ZipFile(TMPL)
tx = z.read("word/document.xml").decode("utf-8")
z.close()
tp = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", tx, re.S)
for i, p in enumerate(tp):
    if 19 <= i <= 28:
        s = ppr(p)
        jc = re.search(r'<w:jc w:val="(\w+)"', s)
        flc = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', s)
        fl = re.search(r'<w:ind[^>]*?w:firstLine="(-?\d+)"', s)
        sp = re.search(r"<w:spacing[^>]*/>", s)
        rs = runs(p)
        def ssz(v):
            return sorted({(-1 if x is None else x) for x in v})

        print("  [%2d] %-28s fonts=%s sz=%s b=%s jc=%s flc=%s fl=%s" % (
            i, ptext(p)[:28].replace("\n", " "),
            sorted({(x["ea"] or "-", x["af"] or "-") for x in rs})[:2],
            ssz({x["sz"] for x in rs}), sorted({x["b"] for x in rs}),
            jc.group(1) if jc else "-", flc.group(1) if flc else "-", fl.group(1) if fl else "-"))
        print("       spacing=%s" % (sp.group(0)[:110] if sp else "-"))

print("\n" + "=" * 84)
print("三、模板页眉页脚实测")
print("=" * 84)
z = zipfile.ZipFile(TMPL)
for n in z.namelist():
    if re.match(r"word/(header|footer)\d*\.xml", n):
        h = z.read(n).decode("utf-8")
        txt = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", h, re.S))
        tabs = re.findall(r"<w:tab/>", h)
        szs = sorted({int(m) / 2.0 for m in re.findall(r'<w:sz w:val="(\d+)"', h)})
        fnt = sorted(set(re.findall(r'w:(?:eastAsia|ascii)="([^"]+)"', h)))
        print("  %-14s 文字=%r" % (n.split("/")[-1], txt[:70]))
        print("        制表位数=%d sz=%s 字体=%s PAGE域=%s" % (len(tabs), szs, fnt, "PAGE" in h))
z.close()

print("\n" + "=" * 84)
print("四、论文 公式形态核查（正文里怎么写的公式）")
print("=" * 84)
z = zipfile.ZipFile(DOC)
dx = z.read("word/document.xml").decode("utf-8")
z.close()
for i, p in enumerate(re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", dx, re.S)):
    t = ptext(p)
    if "式" in t and re.search(r"式\s*[（(]?\s*\d", t):
        rs = runs(p)
        print("  [%4d] %-50s sz=%s" % (i, t[:50].replace("\n", " "), ssz({x["sz"] for x in rs})))

print("\n" + "=" * 84)
print("五、论文 一级标题中显式指定字体的段落")
print("=" * 84)
parts = re.split(r"(<w:tbl>.*?</w:tbl>)", dx, flags=re.S)
gi = 0
for part in parts:
    if part.startswith("<w:tbl>"):
        gi += len(re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S))
        continue
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        if '<w:pStyle w:val="000047"' in p:
            rs = runs(p)
            fnts = {(x["ea"] or "-", x["af"] or "-") for x in rs}
            if fnts != {("-", "-")}:
                print("  [%4d] %-40s fonts=%s sz=%s" % (
                    gi, ptext(p)[:40].replace("\n", " "), sorted(fnts), ssz({x["sz"] for x in rs})))
        gi += 1
