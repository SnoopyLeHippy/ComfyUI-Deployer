@echo off
setlocal

set PYTHON_EXEC=.\ComfyUI_windows_portable\python_embeded\python.exe

REM --- Locate 7z ---
set "SEVENZIP=7z"
where 7z >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "C:\Program Files\7-Zip\7z.exe" (
        set "SEVENZIP=C:\Program Files\7-Zip\7z.exe"
    ) else if exist "C:\Program Files (x86)\7-Zip\7z.exe" (
        set "SEVENZIP=C:\Program Files (x86)\7-Zip\7z.exe"
    ) else (
        echo 7z not found. Please install 7-Zip or add it to your PATH.
        pause
        exit /b 1
    )
)

REM --- Download ComfyUI if needed ---
if not exist ComfyUI_windows_portable_nvidia.7z if not exist ComfyUI_windows_portable (
    echo Downloading ComfyUI archive...
    powershell -Command "(New-Object System.Net.WebClient).DownloadFile('https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z', 'ComfyUI_windows_portable_nvidia.7z')"
) else (
    echo ComfyUI archive or directory already exists, skipping download.
)

REM --- Extract ComfyUI if needed ---
if not exist ComfyUI_windows_portable if exist ComfyUI_windows_portable_nvidia.7z (
    echo Extracting ComfyUI archive...
    "%SEVENZIP%" x ComfyUI_windows_portable_nvidia.7z
) else (
    if exist ComfyUI_windows_portable echo ComfyUI directory already exists, skipping extraction.
)

REM --- Clean up archive ---
if exist ComfyUI_windows_portable_nvidia.7z (
    echo Removing archive...
    del ComfyUI_windows_portable_nvidia.7z
)

REM --- Install dependencies ---
echo Checking dependencies...
%PYTHON_EXEC% -c "import PyQt6" 2>nul
if errorlevel 1 (
    echo PyQt6 not found. Installing...
    %PYTHON_EXEC% -m pip install PyQt6
)
%PYTHON_EXEC% -c "import yaml" 2>nul
if errorlevel 1 (
    echo pyyaml not found. Installing...
    %PYTHON_EXEC% -m pip install pyyaml
)
%PYTHON_EXEC% -c "import uv" 2>nul
if errorlevel 1 (
    echo uv not found. Installing...
    %PYTHON_EXEC% -m pip install uv
)

REM --- Launch ComfyUI Deployer ---
echo Launching ComfyUI Deployer...
%PYTHON_EXEC% -s main.py

pause
