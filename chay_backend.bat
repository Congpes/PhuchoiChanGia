@echo off
title AI-ProGait Backend Server
echo Dang khoi dong Python FastAPI Backend...
set "SINGLE_CAMERA_MODE=false"
set "CAMERA_FRONTAL_INDEX=0"
set "CAMERA_SAGITTAL_INDEX=1"
echo Camera laptop [0]: goc doc/frontal
echo Camera USB    [1]: goc ngang/sagittal
cd backend
.\venv\Scripts\python.exe main.py
pause
