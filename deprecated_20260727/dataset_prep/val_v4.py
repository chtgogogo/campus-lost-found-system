"""Validate the final YOLOv8n weights (models/weights/best.pt) on the held-out val set
and dump mAP metrics to v4_val_metrics.json for the thesis.
"""
import json
import os

from ultralytics import YOLO

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEIGHTS = os.path.join(ROOT, "models", "weights", "best.pt")
DATA = os.path.join(ROOT, "dataset", "final", "data.yaml")
OUT = os.path.join(ROOT, "v4_val_metrics.json")


def main():
    model = YOLO(WEIGHTS)
    metrics = model.val(data=DATA, batch=8, imgsz=640, verbose=True)

    out = {
        "model": "yolov8n (lostfound_v4, 80 epochs, full final dataset)",
        "map50_95": float(metrics.box.map),
        "map50": float(metrics.box.map50),
        "map75": float(metrics.box.map75),
        "per_class_map50_95": [float(x) for x in metrics.box.maps],
        "per_class_map50": [float(x) for x in metrics.box.ap50],
        "names": list(model.names.values()),
        "val_images": int(getattr(metrics.box, "n", 0)),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print("\n===== VALIDATION SUMMARY =====")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
