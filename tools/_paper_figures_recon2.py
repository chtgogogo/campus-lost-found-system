# -*- coding: utf-8 -*-
"""图片精细侦察：段落索引 / rId / 原图像素尺寸 / drawing extent(EMU) / 上下文题注。

用途：为 _paper_figures_replace.py 提供准确的替换锚点与目标尺寸。
"""
from __future__ import annotations

import io
import os
import sys
from typing import Dict, List, Tuple

from docx import Document
from docx.oxml.ns import qn
from PIL import Image

DOCX: str = r"D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文-2026版（7-6）.docx"
EMU_PER_CM: float = 360000.0


def main() -> int:
    if not os.path.exists(DOCX):
        print(f"[ERR] docx 不存在: {DOCX}")
        return 1

    doc = Document(DOCX)
    body = doc.element.body

    rel_info: Dict[str, Tuple[str, int, int, int]] = {}
    idx = 0
    for rel in doc.part.rels.values():
        if "image" not in rel.reltype:
            continue
        idx += 1
        blob = rel.target_part.blob
        try:
            with Image.open(io.BytesIO(blob)) as im:
                w, h = im.size
        except Exception:
            w, h = -1, -1
        rel_info[rel.rId] = (f"fig_{idx:02d}", len(blob), w, h)

    paras = list(body.findall(qn('w:p')))
    texts: List[str] = [p.text for p in paras]

    def next_text(i: int, limit: int = 4) -> str:
        for j in range(i + 1, min(i + 1 + limit, len(texts))):
            t = texts[j].strip()
            if t:
                return t
        return "(无)"

    def prev_text(i: int, limit: int = 4) -> str:
        for j in range(i - 1, max(i - 1 - limit, -1), -1):
            t = texts[j].strip()
            if t:
                return t
        return "(无)"

    print("== 图片段落精细清单 ==")
    for i, p in enumerate(paras):
        blips = list(p.iter(qn('a:blip')))
        if not blips:
            continue
        # extent
        exts = list(p.iter(qn('wp:extent')))
        ext_s = ""
        if exts:
            cx = int(exts[0].get('cx'))
            cy = int(exts[0].get('cy'))
            ext_s = f"cx={cx} cy={cy} ({cx / EMU_PER_CM:.2f}cm x {cy / EMU_PER_CM:.2f}cm)"
        for b in blips:
            rid = b.get(qn('r:embed'))
            name, size, w, h = rel_info.get(rid, ("?", 0, -1, -1))
            print(f"段[{i:3d}] rId={rid:<8} {name} {w}x{h}px {size}B  {ext_s}")
            print(f"        上文: {prev_text(i)[:50]!r}")
            print(f"        下文(题注): {next_text(i)[:50]!r}")

    print("\n== 全文段落（含关键字）扫描 ==")
    import re
    kw = re.compile(r'图\s*\d|YOLO|WebSocket|Redis|轮询|11\s*类|12\s*类|混淆矩阵|keep_status|credit_log|trust_score_log|归一化')
    for i, t in enumerate(texts):
        if kw.search(t):
            print(f"段[{i:3d}] {t[:110]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
