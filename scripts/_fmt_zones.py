# -*- coding: utf-8 -*-
"""确认：Normal 是否存在、正文在用的样式定义、正文 14/16pt 段落身份。"""
import zipfile, re

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"
TPL = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\参考模板拿来填\计算机学院毕业论文（设计）论文模板-应用开发型（人工智能、智能科学与技术专业适用）-2026版（7-6）.docx"


def sx_of(path):
    z = zipfile.ZipFile(path)
    sx = z.read("word/styles.xml").decode("utf-8")
    z.close()
    return sx


def sdef(sx, sid):
    m = re.search(r'<w:style [^>]*w:styleId="%s"[^>]*>(.*?)</w:style>' % re.escape(sid), sx, re.S)
    if not m:
        return None
    b = m.group(1)
    nm = re.search(r'<w:name w:val="([^"]+)"', b)
    rpr = re.search(r"<w:rPr>(.*?)</w:rPr>", b, re.S)
    ppr = re.search(r"<w:pPr>(.*?)</w:pPr>", b, re.S)
    base = re.search(r'<w:basedOn w:val="([^"]+)"', b)
    return dict(name=nm.group(1) if nm else "?",
                basedOn=base.group(1) if base else None,
                rPr=re.sub(r"\s+", " ", rpr.group(1))[:260] if rpr else None,
                pPr=re.sub(r"\s+", " ", ppr.group(1))[:260] if ppr else None)


for path, label in ((DOC, "THESIS"), (TPL, "TEMPLATE")):
    sx = sx_of(path)
    print("\n" + "=" * 80)
    print(label)
    print("=" * 80)
    has_normal = bool(re.search(r'<w:name w:val="Normal"/>|<w:name w:val="Normal">', sx))
    print("含 name=Normal 的样式定义:", has_normal)
    for m in re.finditer(r'<w:style ([^>]*)>', sx):
        attrs = m.group(1)
        sid = re.search(r'w:styleId="([^"]+)"', attrs)
        if sid and "default=\"1\"" in attrs:
            print("  default 样式 styleId =", sid.group(1))
    for sid in ["000058", "000073", "00007a", "000054", "a", "Normal"]:
        d = sdef(sx, sid)
        if d:
            print("\n  [%s] name=%s basedOn=%s" % (sid, d["name"], d["basedOn"]))
            print("     rPr:", d["rPr"])
            print("     pPr:", d["pPr"])

# 正文 14/16pt 段落身份
z = zipfile.ZipFile(DOC)
xml = z.read("word/document.xml").decode("utf-8")
z.close()
parts = re.split(r"(<w:tbl>.*?</w:tbl>)", xml, flags=re.S)


def ptext(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


def psid(p):
    m = re.search(r'<w:pStyle w:val="([^"]+)"', p)
    return m.group(1) if m else None


print("\n" + "=" * 80)
print("正文（表格外）中字号 14/16pt 的段落")
print("=" * 80)
idx = 0
for part in parts:
    if part.startswith("<w:tbl>"):
        continue
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
        idx += 1
        t = ptext(p)
        if not t.strip():
            continue
        sizes = {int(x) / 2.0 for x in re.findall(r"<w:sz w:val=\"(\d+)\"", p)}
        if sizes & {14.0, 16.0}:
            print("  ~[%4d] %-44s sz=%s style=%s" % (idx, t[:44].replace("\n", " "), sorted(sizes), psid(p)))
