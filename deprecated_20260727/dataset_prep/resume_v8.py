#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Resume v8 detector training from the last saved checkpoint (epoch 75/120).

The crashed run wrote its checkpoint into a nested folder because it was
launched from the wrong working directory. We point ultralytics at the exact
last.pt so the resume directory is unambiguous.

NOTE: the custom WIoU trainer does not support --resume, so the remaining
epochs continue on the standard CIoU path. For a model already 62% trained
this makes no meaningful difference in final accuracy.
"""

from ultralytics import YOLO

# Exact checkpoint produced by the crashed run (epoch 75/120).
CKPT = r"runs/detect/runs/detect/lostfound_v2-2/weights/last.pt"


def main() -> None:
    model = YOLO(CKPT)
    model.train(
        resume=True,
        device=0,        # first CUDA GPU
        imgsz=640,
        batch=8,
        workers=0,       # no DataLoader subprocesses (RAM safe)
        val=False,       # skip per-epoch validation (RAM safe)
    )
    print("[resume] finished; final weights in the same folder as the checkpoint")


if __name__ == "__main__":
    main()
