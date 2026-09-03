# -*- coding: utf-8 -*-
import zipfile, re, os

P = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"
print("exists:", os.path.exists(P), os.path.getsize(P) if os.path.exists(P) else "-")
z = zipfile.ZipFile(P)
xml = z.read("word/document.xml").decode("utf-8")
z.close()
paras = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S)


def text(p):
    return "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))


KW = ["归一化", "W_provided", "满分之和", "过高", "偏低", "填写", "完整度", "七维", "七个子维度"]
hits = []
for i, p in enumerate(paras):
    t = text(p)
    if any(kw in t for kw in KW):
        hits.append((i, t))
print("total paras:", len(paras), "hits:", len(hits))
for i, t in hits:
    print("=" * 70)
    print("[para#%d] len=%d" % (i, len(t)))
    print(t[:1500])
