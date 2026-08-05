import zipfile, re, os, shutil, datetime

src = r"D:\Zhuomian\毕业论文\2026年毕业设计论文模板\曹灏天计算机学院毕业论文-2026版（7-6）.docx"
bak = src + f".bak.coverfix2.{datetime.datetime.now():%Y%m%d_%H%M%S}"
shutil.copy(src, bak)
print("备份 ->", os.path.basename(bak))

z = zipfile.ZipFile(src)
doc = z.read('word/document.xml').decode('utf-8', 'ignore')
paras = re.findall(r'<w:p\b.*?</w:p>', doc, re.S)
print("段落数:", len(paras))

def prefix(i):
    p = paras[i]
    return p[:p.index('>') + 1]

def rlabel(t):
    return ('<w:r><w:rPr><w:rFonts w:ascii="宋体" w:hAnsi="宋体" w:eastAsia="宋体" w:hint="eastAsia"/>'
            '<w:b/><w:sz w:val="28"/><w:szCs w:val="32"/></w:rPr>'
            '<w:t xml:space="preserve">' + t + '</w:t></w:r>')

def rul(t):
    return ('<w:r><w:rPr><w:rFonts w:ascii="宋体" w:hAnsi="宋体" w:eastAsia="宋体" w:hint="eastAsia"/>'
            '<w:b/><w:sz w:val="28"/><w:szCs w:val="32"/><w:u w:val="single"/></w:rPr>'
            '<w:t xml:space="preserve">' + t + '</w:t></w:r>')

def rval(t):
    return ('<w:r><w:rPr><w:rFonts w:ascii="宋体" w:hAnsi="宋体" w:eastAsia="宋体" w:hint="eastAsia"/>'
            '<w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>'
            '<w:t>' + t + '</w:t></w:r>')

PPR_FILL = ('<w:pPr><w:spacing w:line="720" w:lineRule="auto"/>'
            '<w:ind w:leftChars="150" w:left="360" w:firstLineChars="446" w:firstLine="1254"/>'
            '<w:rPr><w:rFonts w:ascii="宋体" w:hAnsi="宋体" w:hint="eastAsia"/>'
            '<w:b/><w:sz w:val="28"/><w:szCs w:val="32"/><w:u w:val="single"/></w:rPr></w:pPr>')

PPR_TEACH = ('<w:pPr><w:spacing w:line="720" w:lineRule="auto"/>'
             '<w:ind w:leftChars="150" w:left="360" w:firstLineChars="446" w:firstLine="1254"/>'
             '<w:rPr><w:rFonts w:ascii="黑体" w:eastAsia="黑体" w:hAnsi="宋体" w:hint="eastAsia"/>'
             '<w:b/><w:sz w:val="32"/><w:szCs w:val="32"/><w:u w:val="single"/></w:rPr></w:pPr>')

new8 = prefix(8) + PPR_FILL + rlabel("题    目 ") + rul("                  ") + rval("基于YOLOv8的校园失物招领智能匹配系统") + '</w:p>'
new9 = prefix(9) + PPR_FILL + rlabel("学    院 ") + rul("                  ") + rval("计算机学院") + '</w:p>'
new10 = (prefix(10) + PPR_FILL + rlabel("专    业 ") + rul("                ") + rval("人工智能")
         + rlabel("    年级    ") + rul("                ") + rval("2023") + '</w:p>')
new11 = prefix(11) + PPR_FILL + rlabel("学生姓名") + rul("                  ") + rval("曹灏天") + '</w:p>'
new12 = prefix(12) + PPR_FILL + rlabel("学    号 ") + rul("                  ") + rval("2305500201") + '</w:p>'
new13 = prefix(13) + PPR_TEACH + rlabel("指导教师") + rul("                  ") + rval("陈晓桢") + '</w:p>'

PPR_TITLE = ('<w:pPr><w:spacing w:beforeLines="100" w:before="312" w:afterLines="100" w:after="312"/>'
             '<w:ind w:firstLineChars="97" w:firstLine="310"/>'
             '<w:jc w:val="center"/>'
             '<w:rPr><w:rFonts w:ascii="黑体" w:eastAsia="黑体" w:hAnsi="黑体" w:hint="eastAsia"/>'
             '<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:pPr>')
new16 = (prefix(16) + PPR_TITLE
         + '<w:r><w:rPr><w:rFonts w:ascii="黑体" w:eastAsia="黑体" w:hAnsi="黑体" w:hint="eastAsia"/>'
           '<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr><w:lastRenderedPageBreak/>'
           '<w:t>基于YOLOv8的校园失物招领智能匹配系统</w:t></w:r>' + '</w:p>')

PPR_KAI = ('<w:pPr><w:spacing w:beforeLines="100" w:before="312" w:afterLines="100" w:after="312"/>'
           '<w:ind w:firstLine="560"/>'
           '<w:jc w:val="center"/>'
           '<w:rPr><w:rFonts w:ascii="楷体" w:eastAsia="楷体" w:hAnsi="楷体" w:hint="eastAsia"/>'
           '<w:color w:val="000000"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:pPr>')
new17 = (prefix(17) + PPR_KAI
         + '<w:r><w:rPr><w:rFonts w:ascii="楷体" w:eastAsia="楷体" w:hAnsi="楷体" w:hint="eastAsia"/>'
           '<w:color w:val="000000"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr><w:t>人工智能专业</w:t></w:r>' + '</w:p>')

def kai(t, space=False):
    sp = ' xml:space="preserve"' if space else ''
    return ('<w:r><w:rPr><w:rFonts w:ascii="楷体" w:eastAsia="楷体" w:hAnsi="楷体" w:hint="eastAsia"/>'
            '<w:color w:val="000000"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>'
            '<w:t' + sp + '>' + t + '</w:t></w:r>')

new18 = (prefix(18) + PPR_KAI
         + '<w:commentRangeStart w:id="1"/>'
         + kai("学生：") + kai("曹灏天") + kai("       指导教师：", space=True)
         + '<w:commentRangeEnd w:id="1"/>'
         + '<w:r><w:rPr><w:rStyle w:val="af3"/><w:rFonts w:ascii="楷体" w:eastAsia="楷体" w:hAnsi="楷体" w:hint="eastAsia"/>'
           '<w:color w:val="000000"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr><w:commentReference w:id="1"/></w:r>'
         + kai("陈晓桢") + '</w:p>')

repl = {8: new8, 9: new9, 10: new10, 11: new11, 12: new12, 13: new13, 16: new16, 17: new17, 18: new18}
new_doc = doc
for i, np in repl.items():
    old = paras[i]
    assert old in new_doc, f"[段落 {i}] 未在原文档中找到，替换中止"
    new_doc = new_doc.replace(old, np, 1)
    print(f"OK 段落[{i}] 已替换")

tmp = src + ".tmp"
with zipfile.ZipFile(src, 'r') as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == 'word/document.xml':
            data = new_doc.encode('utf-8')
        zout.writestr(item, data)
os.replace(tmp, src)
print("OK 已写回文档")
