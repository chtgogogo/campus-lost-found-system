# -*- coding: utf-8 -*-
"""正文首行缩进核查：模板 vs 论文（是否 继承2字符 + 手工全角空格 = 4格）。"""
import zipfile, re

DOC = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文.docx"
TMPL = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\参考模板拿来填\计算机学院毕业论文（设计）论文模板-应用开发型（人工智能、智能科学与技术专业适用）-2026版（7-6）.docx"


def ptext(p):
    return "".join(re.findall(r"<w:t(?![A-Za-z])[^>]*>(.*?)</w:t>", p, re.S))


def scan(path, label, rng, n=6):
    z = zipfile.ZipFile(path)
    xml = z.read("word/document.xml").decode("utf-8")
    z.close()
    parts = re.split(r"(<w:tbl>.*?</w:tbl>)", xml, flags=re.S)
    print("\n" + "=" * 84)
    print("%s 正文段落首行缩进（取 %d 段样例）" % (label, n))
    print("=" * 84)
    gi, shown = 0, 0
    stat = {"flc200+空格": 0, "flc200无空格": 0, "无ind+空格": 0, "无ind无空格": 0, "其它": 0}
    for part in parts:
        if part.startswith("<w:tbl>"):
            gi += len(re.findall(r"<w:p[ >].*?</w:p>", part, re.S))
            continue
        for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", part, re.S):
            if rng[0] <= gi <= rng[1]:
                t = ptext(p)
                if t.strip():
                    s = re.search(r"<w:pPr>(.*?)</w:pPr>", p, re.S)
                    s = s.group(1) if s else ""
                    flc = re.search(r'w:firstLineChars="(\d+)"', s)
                    fl = re.search(r'w:firstLine="(-?\d+)"', s)
                    lead = t[:2] == "\u3000\u3000"
                    key = ("flc%s" % flc.group(1) if flc else "无ind") + ("+空格" if lead else "无空格")
                    key = {"flc200+空格": "flc200+空格", "flc200无空格": "flc200无空格",
                           "无ind+空格": "无ind+空格", "无ind无空格": "无ind无空格"}.get(key, "其它")
                    stat[key] += 1
                    if shown < n:
                        print("  [%4d] ind=%-22s 开头双全角空格=%s | %s" % (
                            gi, ("flc=%s fl=%s" % (flc.group(1) if flc else "-",
                                                   fl.group(1) if fl else "-")),
                            lead, t[:34].replace("\n", " ")))
                        shown += 1
            gi += 1
    print("  统计:", {k: v for k, v in stat.items() if v})


scan(TMPL, "【模板】", (30, 90))
scan(DOC, "【论文】", (80, 372))
