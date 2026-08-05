"""
视觉识别诊断脚本 —— 用 best.pt 对指定图片跑推理，输出原始检测结果。
用法: python diagnose_predict.py <图片路径...>
      不传参数则自动扫描 C:/Users/ASUS/Pictures/Screenshots/ 下的 042255/042312/042356/042453
"""
import sys
import os
from pathlib import Path

# 确保项目根目录在 path，以便 import app 模块
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from ultralytics import YOLO
from PIL import Image

# best.pt 11 类顺序（index 0-10）
CLASS_NAMES = [
    "手机", "钱包", "钥匙", "书包", "行李箱",
    "笔记本电脑", "校园卡", "眼镜", "笔记本", "雨伞", "水杯"
]

def load_model():
    weight_path = PROJECT_ROOT / "models" / "weights" / "best.pt"
    if not weight_path.exists():
        print(f"[ERROR] 权重文件不存在: {weight_path}")
        sys.exit(1)
    model = YOLO(str(weight_path))
    print(f"[OK] 模型加载成功: {weight_path}")
    print(f"     类别数: {model.names} ({len(model.names)} 类)")
    return model


def predict_image(model, image_path: Path):
    """对单张图跑 predict，返回所有检测框（不设阈值过滤，看全部原始输出）。"""
    # ultralytics predict 直接接受文件路径
    results = model.predict(source=str(image_path), conf=0.01, verbose=False)
    result = results[0]

    detections = []
    if result.boxes is not None:
        boxes = result.boxes
        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i].item())
            conf = float(boxes.conf[i].item())
            cls_name = model.names.get(cls_id, f"unknown_{cls_id}")
            xywh = boxes.xywhn[i].tolist()  # normalized center_x,center_y,w,h
            detections.append({
                "class_id": cls_id,
                "class_name": cls_name,
                "confidence": round(conf, 4),
                "bbox_xywh_norm": [round(x, 3) for x in xywh],
            })

    # 按 confidence 排序（高→低）
    detections.sort(key=lambda d: d["confidence"], reverse=True)
    return detections


def main():
    model = load_model()

    # 收集要测的图片
    if len(sys.argv) > 1:
        image_paths = [Path(p) for p in sys.argv[1:]]
    else:
        # 默认测用户那 4 张
        screenshot_dir = Path(r"C:\Users\ASUS\Pictures\Screenshots")
        targets = [
            "屏幕截图 2026-07-20 042255.png",   # 钱包
            "屏幕截图 2026-07-20 042312.png",   # 钥匙
            "屏幕截图 2026-07-20 042356.png",   # 雨伞
            "屏幕截图 2026-07-20 042453.png",   # 书
        ]
        image_paths = [screenshot_dir / t for t in targets]

    print(f"\n{'='*70}")
    print(f"批量诊断推理 — 共 {len(image_paths)} 张图 | conf 门槛=0.01(看全部原始输出)")
    print(f"{'='*70}\n")

    total_detections = 0
    for img_path in image_paths:
        if not img_path.exists():
            print(f"[SKIP] 文件不存在: {img_path.name}")
            continue

        dets = predict_image(model, img_path)
        total_detections += len(dets)

        print(f"📷 {img_path.name}")
        print(f"   大小: {Image.open(img_path).size}")
        if not dets:
            print(f"   ⚠️ 无任何检出（模型未发现任何物体）")
        else:
            for i, d in enumerate(dets):
                marker = " ✅ TOP-1" if i == 0 else ""
                bar = "█" * int(d["confidence"] * 30)
                print(f"   [{i+1}] {d['class_name']:6s} | conf={d['confidence']:.4f} | {bar:<30}{marker}")
        print()

    print(f"{'='*70}")
    print(f"总计 {len(image_paths)} 张图, {total_detections} 个检测框")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
