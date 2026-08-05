@echo off
REM ============================================================================
REM  train_v8.cmd  --  Lost-and-Found detector re-training launcher (v8)
REM ============================================================================
REM
REM  WHAT THIS DOES
REM  Re-trains the lost-and-found detector (12 classes) from the existing
REM  models/weights/best.pt checkpoint using WIoU v3 + small-object
REM  augmentation (mosaic / copy-paste / mixup / close-mosaic), producing a
REM  new run named "lostfound_v8" under runs/detect.
REM
REM  CONFIGURATION FOR A MACHINE WITH A CUDA GPU
REM  This script now targets a machine that has an NVIDIA CUDA GPU. The thread
REM  caps below are kept because they stabilize the run and cost nothing on GPU.
REM  We:
REM    * cap every BLAS / OpenMP / Torch thread pool to a single thread (safe)
REM    * train with --workers 0 (no DataLoader subprocesses; safe on 6 GB RAM)
REM    * train on the first CUDA GPU (--device 0)
REM    * use --imgsz 640 and --batch 8 (raise/lower if your VRAM differs)
REM    * skip per-epoch validation (--no-val) to keep the run lean
REM  We never fork background processes and we never launch more than one
REM  python interpreter at a time.
REM
REM  TUNING TIPS (depends on your GPU VRAM):
REM    * --batch  8 -> 16 if you have >= 8 GB VRAM; drop to 4 or 2 on OOM
REM    * --imgsz 640 -> 512 if you hit OOM; 768+ only with lots of VRAM
REM    * --device 0 -> "0,1" if you have two GPUs
REM    * enable WIoU resume: this requires editing the resume block below,
REM      because the custom WIoU trainer does NOT support the normal --resume
REM      path (see the resume block for the exact trade-off).
REM
REM  NOTE ON RESUMING A CPU RUN: if you stop a previous CPU run, its last.pt
REM  triggers the resume branch below, which drops WIoU and uses CIoU. To keep
REM  WIoU, delete runs\detect\lostfound_v8 before launching on the GPU.
REM
REM  After training you can validate a finished run separately, for example:
REM    .venv\Scripts\python.exe tools/dataset_prep/train_yolov8.py ^
REM        --resume --data dataset/final/data.yaml --model models/weights/best.pt
REM ============================================================================

REM Always run from the folder that contains this script (the project root),
REM so that every relative path below resolves correctly no matter where the
REM user double-clicks the file from.
cd /d "%~dp0"

REM --- 1. Make sure the project virtual environment exists --------------------
if not exist ".venv\Scripts\python.exe" (
    powershell -NoProfile -Command "Write-Host '[FATAL] Virtual environment not found: .venv\Scripts\python.exe' -ForegroundColor Red"
    powershell -NoProfile -Command "Write-Host '[FATAL] Please create the venv (.venv) before running this script.' -ForegroundColor Red"
    pause
    exit /b 1
)

REM --- 2. Cap all threading / parallelism (protect low-memory machines) -------
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set TORCH_NUM_THREADS=1
set NUMEXPR_NUM_THREADS=1
set VECLIB_MAXIMUM_THREADS=1

REM --- 3. Auto-resume detection -----------------------------------------------
REM  WIoU training goes through a CUSTOM trainer that does NOT support --resume.
REM  The default (CIoU) path DOES support --resume.
REM  Therefore: if a previous run left weights/last.pt, we RESUME on the CIoU
REM  path -> we DROP --box-loss WIoU and ADD --resume. This trades the WIoU loss
REM  for the ability to continue an interrupted run without losing progress.
REM  On a fresh machine with no prior run, we keep WIoU v3 for the full train.
set "BOX_LOSS_ARGS=--box-loss WIoU"
set "RESUME_ARGS="
if exist "runs\detect\lostfound_v8\weights\last.pt" (
    echo [INFO] Found previous run: runs\detect\lostfound_v8\weights\last.pt
    echo [INFO] Resuming on the CIoU path. --box-loss WIoU is omitted because
    echo [INFO] the custom WIoU trainer does not support --resume.
    set "RESUME_ARGS=--resume"
    set "BOX_LOSS_ARGS="
)

REM --- 4. Launch training -----------------------------------------------------
REM  Memory notes for the arguments below:
REM    --workers 0  : no DataLoader subprocesses (safe on 6 GB RAM)
REM    --device 0   : first CUDA GPU (change to cpu for CPU-only machines)
REM    --imgsz 640  : raised for GPU VRAM; lower to 512 on OOM
REM    --batch 8    : raised for GPU VRAM; lower to 4/2 on OOM, 16 on 8GB+
REM    --no-val     : skip per-epoch validation (saves RAM); validate later
REM    --mosaic / --copy-paste / --mixup / --close-mosaic : small-object aug
.venv\Scripts\python.exe tools/dataset_prep/train_yolov8.py ^
    --model models/weights/best.pt ^
    --data dataset/final/data.yaml ^
    --imgsz 640 ^
    --batch 8 ^
    --workers 0 ^
    --device 0 ^
    --epochs 120 ^
    --patience 30 ^
    --name lostfound_v8 ^
    --project runs/detect ^
    --no-val ^
    --mosaic 1.0 ^
    --copy-paste 0.3 ^
    --mixup 0.1 ^
    --close-mosaic 10 %BOX_LOSS_ARGS% %RESUME_ARGS%

set RC=%errorlevel%

REM --- 5. Report result -------------------------------------------------------
echo.
if %RC%==0 (
    echo ===========================================================================
    echo [OK] Training finished successfully.
    echo [OK] Artifacts are in: runs\detect\lostfound_v8
    echo ===========================================================================
) else (
    echo ===========================================================================
    echo [FAIL] Training exited with code %RC%.
    echo [FAIL] Review the output above for the error.
    echo ===========================================================================
)

pause
