@echo off
title Strategy Tester
echo ============================================
echo    Strategy Tester - Starting Application
echo ============================================
echo.
echo Starting backend server on http://localhost:8001
echo Open http://localhost:8001 in your browser
echo Press Ctrl+C to stop
echo.
cd /d "%~dp0backend"
py -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
pause
