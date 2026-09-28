@echo off
cd /d "%~dp0"
if not exist "backend\venv\Scripts\python.exe" (
    echo Khong tim thay Python cua du an tai backend\venv.
    pause
    exit /b 1
)
"backend\venv\Scripts\python.exe" FSR_Transmitter_2.py --right-calibration calibration/right-20260928-provisional.json
pause
