@echo off
title Strategy Tester
echo ============================================
echo    Strategy Tester - Starting Application
echo ============================================
echo.
echo Starting backend server on http://localhost:5000
echo Open http://localhost:5000 in your browser
echo Press Ctrl+C to stop
echo.
cd /d "%~dp0backend"
py -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
pause
