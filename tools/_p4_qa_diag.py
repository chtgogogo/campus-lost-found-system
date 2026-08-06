# -*- coding: utf-8 -*-
"""诊断：⑦ 模式匹配详情，确认 16 vs 13 差异来源。"""
from docx import Document
from pathlib import Path

DOCX = Path(r"D:/Zhuomian/毕业论文/2026年毕业设计论文模板/曹灏天计算机学院毕业论文-2026版（7-6）.docx")
doc = Document(str(DOCX))
paras = doc.paragraphs

HEADING_FIX_PATTERNS = [
    "匹配模块（MatchService）是算法核心",
    "候选集先经类别主键过滤",
    "发布模块（PublishService）",
    "交接与审计模块（HandoverService",
    "本章明确了以 YOLOv8s + YOLO-World",
    "系统实现采用既定技术栈",
    "核心模块实现思路如下",
    "本章在既定技术栈下完成核心模块编码",
    "测试环境：Windows 平台",
    "测试设计遵循",
    "关键模块测试记录如表 5-1",
    "测试运行结果：全量 334",
    "本章通过单元与端到端测试对系统验证",
]

# 13 个应修复的原始索引（BEFORE 状态 Heading，③ 移动后 286→287）
EXPECTED_FIX_INDICES = {
    211, 212, 216, 217,           # Heading 3
    256, 268, 271, 287, 296, 299, 302, 308, 313,  # Heading 2 (286→287 after move)
}

print("idx | style | pattern | text[:60]")
print("-" * 90)
for i, p in enumerate(paras):
    for pattern in HEADING_FIX_PATTERNS:
        if pattern in p.text:
            in_expected = "★FIX" if i in EXPECTED_FIX_INDICES else "  extra"
            print(f"{i:3d} | {p.style.name:10s} | {in_expected} | {pattern[:25]:25s} | {p.text[:55]}")
            break
