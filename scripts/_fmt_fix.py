# -*- coding: utf-8 -*-
"""
按参考模板批注修复论文格式。用法：
    python scripts/_fmt_fix.py          # dry-run，只打印待改项
    python scripts/_fmt_fix.py --apply  # 实际写入（自动先备份）

批注依据（模板 comments.xml）：
 [2]  页眉 5号居左 + 题目 5号居右
 [5]  中文摘要 5号楷体，"摘要"加粗，固定值20磅，不分段，行头缩进四格
 [14] 一级标题小3标宋黑体
 [18] 正文小4宋体，固定值20磅，两端对齐，首行缩进2字符
 [57] 图注：图片下方黑体五号居中
 [123] 表格 5号宋体，表头 5号黑体
 [8][9] 英文摘要/关键词 Times New Roman 小四
"""
import sys, os, re, zipfile, shutil, datetime

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"
TITLE = "基于YOLOv8的校园失物招领智能匹配系统"
APPLY = "--apply" in sys.argv

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def q(t):
    return "{%s}%s" % (W, t)


# OOXML schema 顺序
PP = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
      "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
      "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
      "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
      "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
      "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"]
RP = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
      "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish",
      "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight",
      "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
      "eastAsianLayout", "specVanish", "oMath"]


def ins_after(parent, tag, new):
    """按 schema 顺序把 new 插入 parent 中 tag 之后（已存在则复用）。"""
    old = parent.find(q(tag))
    if old is not None:
        return old
    new.tag = q(tag)
    idx = PP.index(tag) if tag in PP else RP.index(tag)
    order = PP if tag in PP else RP
    pos = len(parent)
    for i, ch in enumerate(parent):
        tn = ch.tag.split("}")[-1]
        if tn in order and order.index(tn) > idx:
            pos = i
            break
    parent.insert(pos, new)
    return new


def ppr(p):
    return ins_after(p, "pPr", etree.Element(q("pPr")))


def rpr(r):
    return ins_after(r, "rPr", etree.Element(q("rPr")))


def ptext(p):
    return "".join(t.text or "" for t in p.iter(q("t")))


def psid(p):
    s = p.find(q("pPr") + "/" + q("pStyle"))
    return s.get(q("val")) if s is not None else None


def set_font(r, name, sz=None):
    x = rpr(r)
    f = ins_after(x, "rFonts", etree.Element(q("rFonts")))
    f.set(q("ascii"), name)
    f.set(q("hAnsi"), name)
    f.set(q("eastAsia"), name)
    if sz is not None:
        e = ins_after(x, "sz", etree.Element(q("sz")))
        e.set(q("val"), str(int(sz * 2)))
        e = ins_after(x, "szCs", etree.Element(q("szCs")))
        e.set(q("val"), str(int(sz * 2)))


def set_sz(r, pt):
    x = rpr(r)
    for t in ("sz", "szCs"):
        e = ins_after(x, t, etree.Element(q(t)))
        e.set(q("val"), str(int(pt * 2)))


def set_spacing(p, line="400", rule="exact"):
    x = ppr(p)
    s = ins_after(x, "spacing", etree.Element(q("spacing")))
    s.set(q("line"), line)
    s.set(q("lineRule"), rule)


def set_jc(p, v):
    x = ppr(p)
    e = ins_after(x, "jc", etree.Element(q("jc")))
    e.set(q("val"), v)


def set_ind(p, chars=None, twips=None):
    x = ppr(p)
    e = ins_after(x, "ind", etree.Element(q("ind")))
    if chars is not None:
        e.set(q("firstLineChars"), str(chars))
    if twips is not None:
        e.set(q("firstLine"), str(twips))


# ---------- 载入 ----------
z = zipfile.ZipFile(DOC)
data = {n: z.read(n) for n in z.namelist()}
z.close()
root = etree.fromstring(data["word/document.xml"])
body = root.find(q("body"))
paras = list(body.iter(q("p")))
tbl_parent = {}
for tbl in body.iter(q("tbl")):
    for p in tbl.iter(q("p")):
        tbl_parent[id(p)] = tbl

log = []


def note(tag, idx, msg):
    log.append("  [%-14s] %-5s %s" % (tag, idx, msg))


# ---------- 建立索引 ----------
HEADS = {"000047", "000049", "00004b"}
CAPTION = re.compile(r"^\s*(图|表)\s*\d+")

# ================= R1 摘要正文 =================
for i, p in enumerate(paras):
    if i == 21:
        for r in p.findall(q("r")):
            for t in r.findall(q("t")):
                if t.text and t.text.startswith("\u3000\u3000"):
                    note("R1-去空格", i, "摘要正文开头双全角空格 -> 由 flc=400 承担")
                    t.text = t.text[2:]
            set_font(r, "楷体", 10.5)
        set_jc(p, "both")
        set_ind(p, 400, 840)
        set_spacing(p, "400", "exact")
        note("R1-摘要字体", i, "摘要正文 -> 楷体 10.5pt / 两端对齐 / 首行缩进四格")

# ================= R2/R3 表格字号与表头 =================
n_sz = n_hdr = 0
for tbl in body.iter(q("tbl")):
    rows = tbl.findall(q("tr"))
    for ri, tr in enumerate(rows):
        for p in tr.iter(q("p")):
            for r in p.findall(q("r")):
                if not (r.findall(q("t")) and "".join(t.text or "" for t in r.findall(q("t"))).strip()):
                    continue
                x = r.find(q("rPr"))
                cur = None
                if x is not None:
                    e = x.find(q("sz"))
                    cur = int(e.get(q("val"))) / 2 if e is not None else None
                if ri == 0:  # 表头
                    set_font(r, "黑体", 10.5)
                    n_hdr += 1
                elif cur == 9.0:
                    set_sz(r, 10.5)
                    n_sz += 1
note("R2-表格字号", "%d处" % n_sz, "表格内 9.0pt -> 10.5pt（五号）")
note("R3-表头黑体", "%d处" % n_hdr, "表格首行 -> 黑体 10.5pt")

# ================= R4 行距 360/auto -> 400/exact =================
n4 = []
for i, p in enumerate(paras):
    if id(p) in tbl_parent:
        continue
    if psid(p) in HEADS or CAPTION.match(ptext(p) or ""):
        continue
    x = p.find(q("pPr"))
    if x is None:
        continue
    s = x.find(q("spacing"))
    if s is None:
        continue
    if s.get(q("line")) == "360" and (s.get(q("lineRule")) in (None, "auto")):
        n4.append(i)
        set_spacing(p, "400", "exact")
note("R4-行距", "%d段" % len(n4), "1.15倍 -> 固定值20磅 (段号: %s)" % (
    ",".join(map(str, n4[:40])) + ("..." if len(n4) > 40 else "")))

# ================= R5 图注 368 行距异常 =================
for i, p in enumerate(paras):
    if i == 368:
        x = p.find(q("pPr"))
        if x is not None:
            s = x.find(q("spacing"))
            if s is not None:
                val = s.get(q("line"))
                x.remove(s)
                note("R5-图注行距", i, "图5.3 题注 line=%s -> 删除显式，与其它图注一致" % val)

# ================= R6 表注 =================
for i in (240, 283, 319, 451):
    p = paras[i]
    for r in p.findall(q("r")):
        if not (r.findall(q("t")) and "".join(t.text or "" for t in r.findall(q("t"))).strip()):
            continue
        set_font(r, "黑体", 10.5)
    set_jc(p, "center")
    note("R6-表注", i, "表题注 -> 黑体 10.5pt 居中")

# ================= R7 一级标题字体 =================
for i in (90, 372):
    p = paras[i]
    for r in p.findall(q("r")):
        for t in r.findall(q("t")):
            if t.text and t.text.strip():
                pass
        x = r.find(q("rPr"))
        if x is None:
            continue
        f = x.find(q("rFonts"))
        if f is not None and f.get(q("ascii")) == "宋体":
            f.set(q("ascii"), "黑体")
            f.set(q("hAnsi"), "黑体")
            f.set(q("eastAsia"), "黑体")
            note("R7-一级标题", i, "显式宋体 -> 黑体（批注[14] 标宋黑体）")

# ================= R8 英文摘要标签字号 =================
for i in (26, 27):
    p = paras[i]
    for r in p.findall(q("r")):
        if not (r.findall(q("t")) and "".join(t.text or "" for t in r.findall(q("t"))).strip()):
            continue
        x = r.find(q("rPr"))
        has = x is not None and x.find(q("sz")) is not None
        if not has:
            set_sz(r, 12.0)
            note("R8-英文标签", i, "【Abstract/Key words】补 12pt（小四）")

# ================= R9 正文多缩进（继承2字符 + 手工2全角空格 = 4格，应为2格） =================
# 注意：摘要区(19-28) 的「继承2字符+2空格=四格」恰符合批注[5]，必须排除。
n9 = []
for i, p in enumerate(paras):
    if id(p) in tbl_parent or 19 <= i <= 28:
        continue
    if psid(p) in HEADS or CAPTION.match(ptext(p) or ""):
        continue
    if not ptext(p).startswith("\u3000\u3000"):
        continue
    for r in p.findall(q("r")):
        hit = False
        for t in r.findall(q("t")):
            if t.text and t.text.startswith("\u3000\u3000"):
                t.text = t.text[2:]
                hit = True
                break
        if hit:
            n9.append(i)
            break
if n9:
    print("  R9 明细（请核对这些确为正文段落）:")
    for i in n9:
        print("      [%4d] %s" % (i, ptext(paras[i])[:44].replace("\n", " ")))
note("R9-首行缩进", "%d段" % len(n9), "去掉手工双全角空格（继承已是2字符，去掉后=2格）")

# ================= R10 页眉题目占位符 =================
n10 = 0
for name in sorted(data):
    if not re.match(r"word/header\d*\.xml", name):
        continue
    h = etree.fromstring(data[name])
    changed = False
    for t in h.iter(q("t")):
        s = t.text or ""
        if "XXX" in s or ("XX" in s and len(s.strip()) <= 4):
            t.text = s.replace("XXX系统的设计与实现", TITLE).replace("XXX", TITLE).replace("XX", TITLE)
            changed = True
            n10 += 1
            note("R10-页眉", name.split("/")[-1], "占位 %r -> %r" % (s[:32], t.text[:32]))
    if changed:
        data[name] = etree.tostring(h, xml_declaration=True, encoding="UTF-8", standalone=True)
if not n10:
    note("R10-页眉", "0处", "未发现页眉占位符（可能已是真实题目）")

 # ================= R11 表格超版心（批注[123]：表格宽度不能超过版心） =================
sect = re.search(r"<w:sectPr.*?</w:sectPr>", data["word/document.xml"].decode("utf-8"), re.S).group(0)
LIMIT = (int(re.search(r'w:w="(\d+)"', sect).group(1))
         - int(re.search(r'w:left="(\d+)"', sect).group(1))
         - int(re.search(r'w:right="(\d+)"', sect).group(1)))
for ti, tbl in enumerate(body.iter(q("tbl"))):
    g = tbl.find(q("tblGrid"))
    if g is None:
        continue
    grid = g.findall(q("gridCol"))
    cols = [int(c.get(q("w"))) for c in grid]
    tot = sum(cols)
    if tot <= LIMIT:
        continue
    scale = LIMIT / tot
    new = [max(1, int(round(c * scale))) for c in cols]
    new[0] += LIMIT - sum(new)
    for c, nv in zip(grid, new):
        c.set(q("w"), str(nv))
    ntc = 0
    for tr in tbl.findall(q("tr")):
        tcs = tr.findall(q("tc"))
        if len(tcs) != len(new):
            continue
        for k, tc in enumerate(tcs):
            tcPr = tc.find(q("tcPr"))
            if tcPr is None:
                continue
            w = tcPr.find(q("tcW"))
            if w is not None and w.get(q("type")) == "dxa":
                w.set(q("w"), str(new[k]))
                ntc += 1
    note("R11-表格宽度", "表%d" % (ti + 1),
         "%.2fcm -> %.2fcm（超版心，等比缩放；同步 %d 个单元格宽）" % (
             tot / 567, sum(new) / 567, ntc))

# ---------- 输出 ----------
print("=" * 88)
print("格式修复清单  (%s)" % ("APPLY 已写入" if APPLY else "DRY-RUN 预览"))
print("=" * 88)
for l in log:
    print(l)
print("\n合计条目:", len(log))

if APPLY:
    bak = DOC + ".bak.fmtfix_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(DOC, bak)
    print("\n备份 ->", bak)
    for i, p in enumerate(paras):
        p.attrib.pop("__idx", None)
    data["word/document.xml"] = etree.tostring(root, xml_declaration=True,
                                               encoding="UTF-8", standalone=True)
    tmp = DOC + ".tmp"
    zo = zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED)
    for n, b in data.items():
        zo.writestr(n, b)
    zo.close()
    os.replace(tmp, DOC)
    print("已写入 ->", DOC)
