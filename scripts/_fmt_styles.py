# -*- coding: utf-8 -*-
"""列出模板与论文 styles.xml 的全部样式定义，并找出论文中引用但未定义的样式。"""
import zipfile, re
from collections import Counter

TPL = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\参考模板拿来填\计算机学院毕业论文（设计）论文模板-应用开发型（人工智能、智能科学与技术专业适用）-2026版（7-6）.docx"
DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"


def styles(path):
    z = zipfile.ZipFile(path)
    sx = z.read("word/styles.xml").decode("utf-8")
    z.close()
    return sx


def defs(sx):
    out = {}
    for m in re.finditer(r"<w:style ([^>]*)>(.*?)</w:style>", sx, re.S):
        attrs, body = m.group(1), m.group(2)
        sid = re.search(r'w:styleId="([^"]+)"', attrs)
        nm = re.search(r'<w:name w:val="([^"]+)"', body)
        out[sid.group(1) if sid else "?"] = nm.group(1) if nm else "?"
    return out


def used(path):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    z.close()
    return Counter(re.findall(r'<w:pStyle w:val="([^"]+)"', xml))


for path, label in ((TPL, "TEMPLATE"), (DOC, "THESIS")):
    sx = styles(path)
    d = defs(sx)
    u = used(path)
    print("\n" + "=" * 78)
    print("%s  styles.xml 定义 %d 个样式" % (label, len(d)))
    print("=" * 78)
    print("定义的样式:", ", ".join("%s=%s" % (k, v) for k, v in list(d.items())[:40]))
    print("\n文档实际引用:", dict(u))
    missing = {k: v for k, v in u.items() if k not in d}
    print("\n>>> 引用但未定义（悬空样式，会回落 Word 内置默认）:", missing)
