# -*- coding: utf-8 -*-
"""精确体检：用 styleId->name 映射正确识别标题，逐类对照模板批注判定。"""
import zipfile, re
from collections import Counter, defaultdict

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"

# 批注基准（模板 styles.xml 实测 + 批注文字）
BASE = {
    "heading 1": dict(sz=15.0, ea="黑体", jc="center"),
    "heading 2": dict(sz=14.0, ea="黑体", jc="center"),
    "heading 3": dict(sz=12.0, ea="楷体", jc="left"),
    "正文": dict(sz=12.0, ea="宋体", jc="both", line="400", flc="200"),
}


def load(path):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    st = z.read("word/styles.xml").decode("utf-8")
    z.close()
    return re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S), st


def style_map(sx):
    m = {}
    for g in re.finditer(r"<w:style ([^>]*)>(.*?)</w:style>", sx, re.S):
        sid = re.search(r'w:styleId="([^"]+)"', g.group(1))
        nm = re.search(r'<w:name w:val="([^"]+)"', g.group(2))
        if sid:
            m[sid.group(1)] = nm.group(1) if nm else "?"
    return m


def style_def(sx, sid):
    m = re.search(r'<w:style [^>]*w:styleId="%s"[^>]*>(.*?)</w:style>' % re.escape(sid), sx, re.S)
    if not m:
        return {}
    body = m.group(1)
    d = {}
    rpr = re.search(r"<w:rPr>(.*?)</w:rPr>", body, re.S)
    if rpr:
        s = rpr.group(1)
        x = re.search(r'w:eastAsia="([^"]+)"', s)
        d["ea"] = x.group(1) if x else "-"
        x = re.search(r'w:ascii="([^"]+)"', s)
        d["ascii"] = x.group(1) if x else "-"
        x = re.search(r'<w:sz w:val="(\d+)"', s)
        d["sz"] = int(x.group(1)) / 2.0 if x else None
        d["b"] = bool(re.search(r"<w:b/>|<w:b [^>]*/>|<w:bCs/>", s))
    ppr = re.search(r"<w:pPr>(.*?)</w:pPr>", body, re.S)
    if ppr:
        s = ppr.group(1)
        x = re.search(r'<w:jc w:val="([^"]+)"', s)
        d["jc"] = x.group(1) if x else "-"
        x = re.search(r'<w:spacing[^>]*?w:line="(\d+)"', s)
        r = re.search(r'<w:spacing[^>]*?w:lineRule="(\w+)"', s)
        d["line"] = (x.group(1) + "/" + r.group(1)) if (x and r) else (x.group(1) if x else "-")
        x = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', s)
        d["flc"] = x.group(1) if x else "-"
    return d


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
        ea = ascii_f = None
        sz = None
        m = re.search(r"<w:rFonts[^>]*/>", r) or re.search(r"<w:rFonts[^>]*>.*?</w:rFonts>", r, re.S)
        if m:
            f = m.group(0)
            x = re.search(r'w:eastAsia="([^"]+)"', f)
            ea = x.group(1) if x else None
            x = re.search(r'w:ascii="([^"]+)"', f)
            ascii_f = x.group(1) if x else None
        m = re.search(r'<w:sz w:val="(\d+)"', r)
        if m:
            sz = int(m.group(1)) / 2.0
        out.append((t, ea or "-", ascii_f or "-", sz))
    return out


ps, sx = load(DOC)
smap = style_map(sx)
print("=" * 90)
print("一、标题类样式定义（对照批注[14]：H1小3黑体居中 / H2 4号黑体居中 / H3 小4楷体居左）")
print("=" * 90)
for sid, nm in smap.items():
    if nm.lower().startswith("heading") or "标题" in nm:
        d = style_def(sx, sid)
        print("  %-8s %-22s ea=%-6s ascii=%-8s sz=%-6s bold=%-5s jc=%-7s line=%-10s flc=%s"
              % (sid, nm, d.get("ea", "-"), d.get("ascii", "-"), d.get("sz"),
                 d.get("b"), d.get("jc", "-"), d.get("line", "-"), d.get("flc", "-")))

print("\n" + "=" * 90)
print("二、正文档位：无 pStyle 段落的 run 级格式统计")
print("=" * 90)
nostyle = [p for p in ps if psid(p) is None and ptext(p).strip()]
print("无样式段落数:", len(nostyle))
fontc, szc, jcc, linec, flcc = Counter(), Counter(), Counter(), Counter(), Counter()
for p in nostyle:
    rs = runs(p)
    if not rs:
        continue
    fontc.update((x[1], x[2]) for x in rs)
    szc.update(x[3] for x in rs)
    s = ppr(p)
    x = re.search(r'<w:jc w:val="([^"]+)"', s)
    jcc[x.group(1) if x else "-"] += 1
    x = re.search(r'<w:spacing[^>]*?w:line="(\d+)"', s)
    r = re.search(r'<w:spacing[^>]*?w:lineRule="(\w+)"', s)
    linec[(x.group(1) + "/" + r.group(1)) if (x and r) else (x.group(1) if x else "-")] += 1
    x = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', s)
    flcc[x.group(1) if x else "-"] += 1
print("  字体(ea/ascii) top:", fontc.most_common(5))
print("  字号 top:", szc.most_common(5))
print("  对齐:", jcc.most_common(5))
print("  行距:", linec.most_common(5))
print("  首行缩进字符:", flcc.most_common(5))

print("\n" + "=" * 90)
print("三、无字体/无字号设置的段落（继承链外，需显式修正的目标）")
print("=" * 90)
targets = []
for i, p in enumerate(ps):
    t = ptext(p)
    if not t.strip():
        continue
    rs = runs(p)
    if not rs:
        continue
    nofont = all(x[1] == "-" and x[2] == "-" for x in rs)
    nosz = all(x[3] is None for x in rs)
    if nofont or nosz:
        targets.append((i, t, nofont, nosz, psid(p)))
print("总数:", len(targets))
print("  前 25 条：")
for i, t, nf, ns, sid in targets[:25]:
    print("   [%4d] %-38s nofont=%s nosz=%s style=%s" % (i, t[:38].replace("\n", " "), nf, ns, sid))
