@echo off
echo ══════════════════════════════════════
echo        MTF Tester — Starting...
echo ══════════════════════════════════════
echo.

cd /d "%~dp0\backend"

echo.
echo Starting server at http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.

python -m uvicorn main.app:app --host 127.0.0.1 --port 8000 --reload

pause
