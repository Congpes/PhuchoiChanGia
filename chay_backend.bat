@echo off
setlocal
title AI-ProGait Backend Server
echo Dang khoi dong Python FastAPI Backend...
set "SINGLE_CAMERA_MODE=false"
set "CAMERA_FRONTAL_INDEX="
set "CAMERA_SAGITTAL_INDEX="
echo Camera se duoc chon trong man Scan sau khi backend khoi dong.
echo Neu co 2 webcam ngoai, hay chon 2 anh thu cua webcam ngoai.
cd /d "%~dp0backend"
if not exist ".matplotlib" mkdir ".matplotlib"
set "MPLCONFIGDIR=%CD%\.matplotlib"
if not exist "venv\Scripts\python.exe" (
    echo.
    echo LOI: Chua co moi truong Python tai backend\venv.
    echo Hay chay phan cai dat backend trong Runguide.md truoc.
    pause
    exit /b 1
)
.\venv\Scripts\python.exe main.py
pause
