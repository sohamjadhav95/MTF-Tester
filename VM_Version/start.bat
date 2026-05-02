@echo off
echo ══════════════════════════════════════
echo        MTF Tester — Getting Updates
echo ══════════════════════════════════════
echo.

cd /d "%~dp0"
echo Fetching and pulling latest code...
git fetch
git pull

echo.
echo ══════════════════════════════════════
echo        MTF Tester — Starting...
echo ══════════════════════════════════════
echo.

:: Activate virtual environment
if exist "%~dp0..\mtf-env\Scripts\activate.bat" (
    call "%~dp0..\mtf-env\Scripts\activate.bat"
    echo Activated mtf-env virtual environment.
) else if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
    echo Activated local venv virtual environment.
) else (
    echo WARNING: Virtual environment not found at expected locations. Running with default python...
)

cd /d "%~dp0\backend"

echo.
echo Starting server at http://0.0.0.0:5000
echo Press Ctrl+C to stop.
echo.

python -m uvicorn main.app:app --host 0.0.0.0 --port 5000 --reload

pause
