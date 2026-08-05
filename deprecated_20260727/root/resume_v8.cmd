@echo off
REM ============================================================
REM  resume_v8.cmd - RESUME v8 detector training from epoch 75/120
REM
REM  WHAT THIS DOES
REM    Continues the crashed run from its exact checkpoint. The model
REM    keeps all 75 epochs of progress and trains the remaining ~45.
REM
REM  BEFORE YOU RUN
REM    1. CLOSE any RAM-heavy background apps first - especially the
REM       "Watt Toolkit" / GitHub accelerator. It squeezed system RAM
REM       mid-run and caused the previous numpy alloc crash.
REM    2. Do NOT double-click train_v8.cmd - that starts a FRESH run
REM       from epoch 0 and would waste the 75/120 progress.
REM
REM  The checkpoint lives in a nested folder (a CWD bug from the earlier
REM  crashed run). resume_v8.py points ultralytics at the exact last.pt
REM  so there is no directory ambiguity.
REM ============================================================

cd /d "%~dp0"

REM --- thread caps (avoid parallel / process blow-up) ---
set OMP_NUM_THREADS=1
set MKL_NUM_THREADS=1
set OPENBLAS_NUM_THREADS=1
set TORCH_NUM_THREADS=1
set NUMEXPR_NUM_THREADS=1
set VECLIB_MAXIMUM_THREADS=1

if not exist ".venv\Scripts\python.exe" (
    powershell -Command "Write-Host -ForegroundColor Red '[FATAL] .venv not found. Run setup first.'"
    pause
    exit /b 1
)

echo [INFO] Resuming from epoch 75/120 (checkpoint: runs/detect/runs/detect/lostfound_v2-2/weights/last.pt)
.venv\Scripts\python.exe tools\dataset_prep\resume_v8.py
set RC=%errorlevel%

if %RC%==0 (
    echo.
    echo [OK] Resume finished. Final weights in runs/detect/runs/detect/lostfound_v2-2/weights/
) else (
    echo.
    echo [FAIL] Resume exited with code %RC%. Check the output above.
    echo [FAIL] If it is an OOM, lower --batch (8 to 4) / --imgsz (640 to 512) in tools/dataset_prep/resume_v8.py
)
pause
