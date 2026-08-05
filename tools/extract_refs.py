import os, glob, pdfplumber

src_dir = r"D:\Zhuomian\毕业论文\论文参考文献原文"
out_dir = r"E:\xuexixiangguan\pythonProject\gongcheng\失物招领系统\tools\ref_text"
os.makedirs(out_dir, exist_ok=True)

# 文件 -> 参考文献编号/标签
mapping = {
    "同形拼布图谱快速参数化设计原理及平台搭建_吴可.pdf": "ref01_吴可",
    "YOLO系列目标检测算法综述_徐彦威.pdf": "ref09_徐彦威",
    "一种基于词嵌入和多重语义关系的词语相似度计算方法_关慧.pdf": "ref12_关慧",
    "基于SpringBoot+Vue+Uni-app框架的校园失物招领系统_朱志慧.pdf": "ref06_朱志慧",
    "基于Transformer的交互式问答双通道语义检索_蔡志鹏.pdf": "ref11_蔡志鹏",
    "基于Vue3的数据申请管理系统设计与实现_邹聪.pdf": "ref10_邹聪",
    "改进YOLOv8s的轻量级无人机航拍小目标检测算法_翟亚红.pdf": "ref04_翟亚红",
    "面向无人机航拍小目标检测的轻量级YOLOv8检测算法_李岩超.pdf": "ref03_李岩超",
    "YOLO-World-CVPR2024.pdf": "ref13_YOLOWorld",
}

for fname, label in mapping.items():
    path = os.path.join(src_dir, fname)
    if not os.path.exists(path):
        print("MISSING:", fname); continue
    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for i, pg in enumerate(pdf.pages):
                t = pg.extract_text() or ""
                pages.append(f"\n===== PAGE {i+1} =====\n" + t)
        text = "\n".join(pages)
        out = os.path.join(out_dir, label + ".txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"OK {label}: {len(pdf.pages)} pages, {len(text)} chars -> {os.path.basename(out)}")
    except Exception as e:
        print(f"ERR {label}: {e}")
