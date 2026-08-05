"""Validate lostfound_v5 (12 classes) on dataset/final and dump metrics to v12_val_metrics.json.

Class groups (per data.yaml order):
  COCO common   : phone(0) backpack(3) suitcase(4) laptop(5) glasses(7) notebook(8) umbrella(9) bottle(10)
  Campus-specific: wallet(1) keys(2) campus_card(6)
  Other (兜底)   : other(11)

NOTE: all execution is wrapped in main() + `if __name__ == "__main__"` so that
Windows multiprocessing (ultralytics spawns dataloader workers) does not re-execute
the module top-level and hit the freeze_support() recursion error.
"""
import os
import sys
import json


def main():
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)

    from ultralytics import YOLO

    CKPT = "runs/detect/lostfound_v5/weights/best.pt"
    DATA = "dataset/final/data.yaml"
    OUT = "v12_val_metrics.json"

    # workers=0 -> single-process dataloader, avoids Windows multiprocessing freeze_support issue
    model = YOLO(CKPT)
    metrics = model.val(data=DATA, batch=8, imgsz=640, plots=False, save_json=False, workers=0)

    names = model.names
    n = len(names)
    m50 = float(metrics.box.map50)
    m5095 = float(metrics.box.map)
    m75 = float(metrics.box.map75)
    per50 = [float(x) for x in metrics.box.ap50]
    per5095 = [float(x) for x in metrics.box.maps]

    coco_idx = [0, 3, 4, 5, 7, 8, 9, 10]
    campus_idx = [1, 2, 6]
    other_idx = [11]

    def mean(idxs, arr):
        return sum(arr[i] for i in idxs) / len(idxs)

    out = {
        "names": {int(k): v for k, v in names.items()},
        "n": n,
        "map50": m50,
        "map50_95": m5095,
        "map75": m75,
        "per_class_map50": per50,
        "per_class_map50_95": per5095,
        "coco_idx": coco_idx,
        "campus_idx": campus_idx,
        "other_idx": other_idx,
        "coco_map50": mean(coco_idx, per50),
        "coco_map50_95": mean(coco_idx, per5095),
        "campus_map50": mean(campus_idx, per50),
        "campus_map50_95": mean(campus_idx, per5095),
        "other_map50": mean(other_idx, per50),
        "other_map50_95": mean(other_idx, per5095),
    }
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    print("saved", OUT)
    print("overall mAP@0.5=%.4f  mAP@0.5:0.95=%.4f  mAP@0.75=%.4f" % (m50, m5095, m75))
    print("COCO   mAP@0.5=%.4f  mAP@0.5:0.95=%.4f" % (out["coco_map50"], out["coco_map50_95"]))
    print("CAMPUS mAP@0.5=%.4f  mAP@0.5:0.95=%.4f" % (out["campus_map50"], out["campus_map50_95"]))
    print("OTHER  mAP@0.5=%.4f  mAP@0.5:0.95=%.4f" % (out["other_map50"], out["other_map50_95"]))


if __name__ == "__main__":
    main()
