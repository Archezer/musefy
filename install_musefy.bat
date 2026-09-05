@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

title Musefy setup

if not exist "pyproject.toml" (
    echo [ERROR] pyproject.toml was not found.
    echo Run this installer from the Musefy project directory.
    exit /b 1
)

set "MUSEFY_PYTHON_VERSION=3.12"

call :find_uv
if not defined MUSEFY_UV_EXE (
    echo [INFO] uv was not found. Installing the official uv bootstrapper...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference = 'Stop'; irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo [ERROR] Could not install uv.
        exit /b 1
    )
    call :find_uv
)
if not defined MUSEFY_UV_EXE (
    echo [ERROR] uv was installed but could not be found.
    echo Open a new terminal and run this file again.
    exit /b 1
)

echo.
echo ========================================
echo              Musefy setup
echo ========================================
echo.

echo [1/5] Preparing managed Python %MUSEFY_PYTHON_VERSION%...
"%MUSEFY_UV_EXE%" python install %MUSEFY_PYTHON_VERSION%
if errorlevel 1 (
    echo [ERROR] Could not install or locate Python %MUSEFY_PYTHON_VERSION%.
    exit /b 1
)

if defined MUSEFY_FORCE_PROFILE (
    set "MUSEFY_PROFILE_FORCED=1"
    set "MUSEFY_INSTALL_PROFILE=%MUSEFY_FORCE_PROFILE%"
    if /I "%MUSEFY_FORCE_PROFILE%"=="cpu" goto :profile_selected
    if /I "%MUSEFY_FORCE_PROFILE%"=="cuda" goto :profile_selected
    echo [ERROR] MUSEFY_FORCE_PROFILE must be cpu or cuda.
    exit /b 1
)

set "MUSEFY_INSTALL_PROFILE=cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
    nvidia-smi -L >nul 2>&1
    if not errorlevel 1 set "MUSEFY_INSTALL_PROFILE=cuda"
)

:profile_selected
echo Hardware profile: %MUSEFY_INSTALL_PROFILE%
echo A separate CUDA Toolkit is not required for the packaged CUDA wheels.

echo [2/5] Installing FFmpeg...
call :ensure_ffmpeg
if errorlevel 1 exit /b 1

echo [3/5] Installing locked Python dependencies...
"%MUSEFY_UV_EXE%" sync --locked --no-dev --python %MUSEFY_PYTHON_VERSION% --extra %MUSEFY_INSTALL_PROFILE%
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
)

echo [4/5] Verifying PyTorch and ONNX Runtime...
call :verify_runtime
if not errorlevel 1 goto :download_models

if /I not "%MUSEFY_INSTALL_PROFILE%"=="cuda" goto :failure

if defined MUSEFY_PROFILE_FORCED (
    echo [ERROR] The forced CUDA profile could not start CUDA.
    echo Update the NVIDIA driver or run without MUSEFY_FORCE_PROFILE for CPU fallback.
    goto :failure
)

echo [WARNING] CUDA dependencies were installed, but CUDA could not start.
echo [WARNING] This usually means that the NVIDIA driver is missing or too old.
echo [INFO] Falling back to the CPU profile. CUDA Toolkit installation is not required.
"%MUSEFY_UV_EXE%" sync --locked --no-dev --python %MUSEFY_PYTHON_VERSION% --extra cpu
if errorlevel 1 goto :failure
set "MUSEFY_INSTALL_PROFILE=cpu"
call :verify_runtime
if errorlevel 1 goto :failure

:download_models
echo [5/5] Downloading required models and local MERT snapshot...
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The project environment was not created.
    exit /b 1
)
".venv\Scripts\python.exe" "scripts\download_models.py"
if errorlevel 1 (
    echo [ERROR] Model installation failed.
    exit /b 1
)

echo.
echo Musefy is ready with the %MUSEFY_INSTALL_PROFILE% profile.
echo Start it with: .venv\Scripts\python.exe -m app.desktop
echo The browser extension is in: extensions\vk-spotify-playlist-exporter
exit /b 0

:verify_runtime
"%MUSEFY_UV_EXE%" run --no-dev --python %MUSEFY_PYTHON_VERSION% --extra %MUSEFY_INSTALL_PROFILE% python -c "import sys, torch, onnxruntime as ort; cuda_available = torch.cuda.is_available(); providers = ort.get_available_providers(); ort_cuda_available = 'CUDAExecutionProvider' in providers; print('PyTorch:', torch.__version__); print('CUDA available:', cuda_available); print('ONNX providers:', ', '.join(providers)); sys.exit(0 if '%MUSEFY_INSTALL_PROFILE%' == 'cpu' or (cuda_available and ort_cuda_available) else 1)"
exit /b %errorlevel%

:ensure_ffmpeg
where ffmpeg >nul 2>nul
if not errorlevel 1 exit /b 0

where winget >nul 2>nul
if errorlevel 1 (
    echo [ERROR] FFmpeg is missing and winget was not found.
    echo Install the Windows App Installer, then run this file again.
    exit /b 1
)

winget install --id Gyan.FFmpeg.Shared --exact --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo [ERROR] FFmpeg installation failed.
    exit /b 1
)

set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
where ffmpeg >nul 2>nul
if not errorlevel 1 exit /b 0

echo [WARNING] FFmpeg was installed, but this terminal cannot see it yet.
echo The packaged application can locate the WinGet installation automatically.
exit /b 0

:find_uv
set "MUSEFY_UV_EXE="
for /f "delims=" %%P in ('where uv 2^>nul') do if not defined MUSEFY_UV_EXE set "MUSEFY_UV_EXE=%%P"
if not defined MUSEFY_UV_EXE if exist "%USERPROFILE%\.local\bin\uv.exe" set "MUSEFY_UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not defined MUSEFY_UV_EXE if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "MUSEFY_UV_EXE=%USERPROFILE%\.cargo\bin\uv.exe"
exit /b 0

:failure
echo [ERROR] Musefy environment verification failed.
exit /b 1
