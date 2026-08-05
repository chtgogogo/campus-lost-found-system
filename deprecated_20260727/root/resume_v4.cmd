@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [FATAL] .venv\Scripts\python.exe not found in this folder.
  echo         This project trains with its own virtual environment.
  pause
  exit /b 1
)
echo ============================================================
echo  resume_v4 : continue lostfound_v4 from epoch 68+ (val off)
echo ============================================================
echo.
.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('runs/detect/runs/detect/lostfound_v4/weights/last.pt').train(resume=True, val=False)"
set RC=%errorlevel%
echo.
if %RC%==0 (
  echo [OK] Training finished successfully.
) else (
  echo [FAIL] Training exited with code %RC% - read the error text above.
)
echo.
echo IMPORTANT: do NOT press a key yet. Read the output above first.
echo  - If you see a progress bar / epoch numbers, training is RUNNING. Leave it.
echo  - If you see red error text and [FAIL], copy that text back to me.
echo.
pause
