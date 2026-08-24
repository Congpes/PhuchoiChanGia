@echo off
setlocal
title AI-ProGait Flutter Frontend
cd /d "%~dp0frontend_app"
if not exist ".dart_tool\package_config.json" (
    echo Chua co dependency cache. Dang chay flutter pub get...
    flutter pub get
    if errorlevel 1 (
        echo.
        echo LOI: Khong the khoi phuc dependency Flutter.
        pause
        exit /b 1
    )
)
echo Dang khoi dong Flutter Web...
flutter run -d chrome --no-pub --no-web-resources-cdn
pause
