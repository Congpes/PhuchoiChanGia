@echo off
setlocal
title AI-ProGait Flutter Frontend
cd /d "%~dp0frontend_app"
echo Dang khoi dong Flutter Web bang cache hien co...
flutter run -d chrome --no-pub
pause
