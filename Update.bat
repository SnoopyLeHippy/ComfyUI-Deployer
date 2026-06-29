@echo off
setlocal

echo Updating ComfyUI-Deployer...

where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Git not found. Please install Git or add it to your PATH.
    pause
    exit /b 1
)

git pull
if %ERRORLEVEL% NEQ 0 (
    echo Update failed. Check the errors above.
    pause
    exit /b 1
)

echo.
echo ComfyUI-Deployer updated successfully.
pause
