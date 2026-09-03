# -*- coding: utf-8 -*-
"""全量格式体检：按样式/区域统计字体、字号、行距、对齐，对照模板批注判定。"""
import zipfile, re, os
from collections import Counter, defaultdict

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"


def load(path):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    z.close()
    return re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S)


def ptext(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


def pstyle(p):
    m = re.search(r'<w:pStyle w:val="([^"]+)"', p)
    return m.group(1) if m else "Normal"


def ppr(p):
    m = re.search(r"<w:pPr>(.*?)</w:pPr>", p, re.S)
    return m.group(1) if m else ""


def jc(p):
    m = re.search(r'<w:jc w:val="([^"]+)"', ppr(p))
    return m.group(1) if m else "-"


def line(p):
    s = ppr(p)
    m = re.search(r'<w:spacing[^>]*?w:line="(\d+)"', s)
    rule = re.search(r'<w:spacing[^>]*?w:lineRule="(\w+)"', s)
    if m:
        return m.group(1) + ("/" + rule.group(1) if rule else "")
    return "-"


def flc(p):
    m = re.search(r'<w:ind[^>]*?w:firstLineChars="(\d+)"', ppr(p))
    return m.group(1) if m else "-"


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
        b = bool(re.search(r"<w:b/>|<w:b [^>]*/>", r))
        out.append((t, ea or "-", ascii_f or "-", sz, b))
    return out


def summarize(p):
    rs = runs(p)
    if not rs:
        return None
    fonts = Counter((x[1], x[2]) for x in rs)
    sizes = Counter(x[3] for x in rs)
    bold = any(x[4] for x in rs)
    top_font = fonts.most_common(1)[0][0]
    top_sz = sizes.most_common(1)[0][0]
    return {"font": top_font, "sz": top_sz, "bold": bold, "fonts": dict(fonts)}


def classify(i, t, style):
    s = t.strip()
    if style.startswith("TOC") or style.startswith("00006") or style.startswith("00007"):
        return "TOC"
    if re.match(r"^图\s*\d+[.\-]", s):
        return "图注"
    if re.match(r"^表\s*\d+[.\-]", s):
        return "表注"
    if re.match(r"^摘\s*要|^【摘\s*要】", s):
        return "摘要标题"
    if re.match(r"^关键词|^【关键词】|^Key\s*words", s):
        return "关键词"
    if re.match(r"^【?Abstract】?", s):
        return "Abstract标题"
    if style.lower().startswith("heading"):
        lvl = re.search(r"(\d+)", style)
        return "H" + (lvl.group(1) if lvl else "?")
    if re.match(r"^第[一二三四五六七八九十]+章", s) and len(s) < 40:
        return "疑似H1"
    if re.match(r"^\d+(\.\d+){0,2}\s+\S", s) and len(s) < 40:
        return "疑似HX"
    if re.match(r"^参考文献", s) and len(s) < 20:
        return "参考文献标题"
    return "正文"


ps = load(DOC)
print("总段落:", len(ps))

groups = defaultdict(list)
for i, p in enumerate(ps):
    t = ptext(p)
    if not t.strip():
        continue
    sm = summarize(p)
    if not sm:
        continue
    cat = classify(i, t, pstyle(p))
    groups[cat].append((i, t, sm["font"], sm["sz"], sm["bold"], jc(p), line(p), flc(p), pstyle(p)))

print("\n" + "=" * 92)
print("分类 / 数量 / 主流(字体ea,字体ascii) / 主流字号 / 加粗 / 对齐 / 行距 / 首行缩进字符")
print("=" * 92)
for cat in sorted(groups, key=lambda c: -len(groups[c])):
    rows = groups[cat]
    fc = Counter((r[2], r[3]) for r in rows)
    jcc = Counter(r[5] for r in rows)
    lc = Counter(r[6] for r in rows)
    fc2 = Counter(r[7] for r in rows)
    print("\n【%s】 n=%d" % (cat, len(rows)))
    print("   (ea/ascii, 字号): %s" % fc.most_common(4))
    print("   对齐=%s 行距=%s 首行缩进=%s" % (jcc.most_common(3), lc.most_common(3), fc2.most_common(3)))
    if cat in ("图注", "表注", "疑似H1", "疑似HX", "摘要标题", "关键词", "Abstract标题"):
        for r in rows[:8]:
            print("     [%d] %s | %s %s bold=%s jc=%s line=%s flc=%s style=%s"
                  % (r[0], r[1][:26], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
