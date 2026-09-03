# -*- coding: utf-8 -*-
import zipfile, re
DOC = r"D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文.docx"
z = zipfile.ZipFile(DOC)
sx = z.read("word/styles.xml").decode("utf-8")
z.close()
m = re.search(r'<w:style [^>]*w:styleId="000046"[^>]*>(.*?)</w:style>', sx, re.S)
print("=== 论文 Normal (000046) 原始定义 ===")
print(m.group(0) if m else "NOT FOUND")
print()
for sid in ["000047","000049","00004b"]:
    mm = re.search(r'<w:style [^>]*w:styleId="%s"[^>]*>(.*?)</w:style>' % sid, sx, re.S)
    print("=== %s ===" % sid)
    print(mm.group(0)[:900] if mm else "NOT FOUND")
    print()
