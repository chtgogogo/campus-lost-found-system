@echo off
cd /d "%~dp0"
echo Starting backend (port 8000) and frontend (port 5175)...
start "backend-8000" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
start "frontend-5175" cmd /k "cd web && npm run dev"
echo Done. Two windows opened - keep them open.
echo Frontend: http://localhost:5175  (RAG assistant uses 5174 - no conflict)
timeout /t 3 >nul
