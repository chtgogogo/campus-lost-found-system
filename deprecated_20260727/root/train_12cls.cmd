@echo off
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [FATAL] %PY% not found in this project.
  pause
  exit /b 1
)
echo ============================================================
echo  train_12cls : 12-class YOLOv8n (lostfound_v5) 80 epochs
echo  start: %DATE% %TIME%
echo ============================================================
%PY% tools/dataset_prep/train_12cls.py
set RC=%ERRORLEVEL%
echo ============================================================
if %RC%==0 (
  echo [OK] Training finished successfully.
) else (
  echo [FAIL] Training exited with code %RC%.
)
echo  end: %DATE% %TIME%
echo  IMPORTANT: read the output above before pressing any key.
echo  This window is independent of WorkBuddy - closing WorkBuddy will NOT stop it.
pause
