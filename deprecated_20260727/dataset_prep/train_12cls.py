"""
Train lostfound_v5: 12 classes (incl. 'other' as class 11) from yolov8n pretrained.

- Starts from yolov8n.pt (COCO-pretrained backbone/neck); the detection head is rebuilt
  to nc=12 read from dataset/final/data.yaml, so 'other' is learned from scratch while
  low-level features are transferred.
- val=False: skip per-epoch validation (the previous OOM happened in the validation step),
  validate separately after training with val_12cls.py.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from ultralytics import YOLO

CKPT = "models/weights/yolov8n.pt"
DATA = "dataset/final/data.yaml"
NAME = "lostfound_v5"

print("[INFO] cwd =", os.getcwd())
print("[INFO] training %s from %s (nc read from %s)" % (NAME, CKPT, DATA))

model = YOLO(CKPT)
model.train(
    data=DATA,
    epochs=80,
    imgsz=640,
    batch=16,
    workers=0,            # single worker on Windows avoids multiprocessing memory spikes
    cache="disk",         # cache images/labels to E: disk (NOT RAM) to cap memory creep
    name=NAME,
    val=False,            # validate separately to avoid OOM
    exist_ok=True,
    seed=0,
    close_mosaic=10,      # disable mosaic in last 10 epochs for better mAP
)
print("[DONE] training finished; weights at runs/detect/%s/weights/" % NAME)
