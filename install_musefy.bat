@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Musefy setup

if not exist "pyproject.toml" (
    echo [ERROR] pyproject.toml was not found.
    echo Run this installer from the Musefy project directory.
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found in PATH.
    echo Install uv, open a new terminal, and run this script again.
    exit /b 1
)

echo.
echo ========================================
echo              Musefy setup
echo ========================================
echo.

if defined MUSEFY_FORCE_PROFILE (
    set "MUSEFY_INSTALL_PROFILE=%MUSEFY_FORCE_PROFILE%"
    if /I "%MUSEFY_FORCE_PROFILE%"=="cpu" goto :profile_selected
    if /I "%MUSEFY_FORCE_PROFILE%"=="cuda" goto :profile_selected
    echo [ERROR] MUSEFY_FORCE_PROFILE must be cpu or cuda.
    exit /b 1
) else (
    set "MUSEFY_INSTALL_PROFILE=cpu"
    where nvidia-smi >nul 2>nul
    if not errorlevel 1 (
        nvidia-smi -L >nul 2>&1
        if not errorlevel 1 set "MUSEFY_INSTALL_PROFILE=cuda"
    )
)

:profile_selected
echo Hardware profile: %MUSEFY_INSTALL_PROFILE%
echo Installing runtime dependencies...
uv sync --locked --no-dev --extra %MUSEFY_INSTALL_PROFILE%
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    exit /b 1
)

echo Verifying PyTorch and ONNX Runtime...
uv run --no-dev --extra %MUSEFY_INSTALL_PROFILE% python -c "import sys, torch, onnxruntime as ort; cuda_available = torch.cuda.is_available(); providers = ort.get_available_providers(); ort_cuda_available = 'CUDAExecutionProvider' in providers; print('PyTorch:', torch.__version__); print('CUDA available:', cuda_available); print('ONNX providers:', ', '.join(providers)); sys.exit(0 if '%MUSEFY_INSTALL_PROFILE%' == 'cpu' or (cuda_available and ort_cuda_available) else 1)"
if not errorlevel 1 goto :success

if /I not "%MUSEFY_INSTALL_PROFILE%"=="cuda" goto :failure

echo [WARNING] NVIDIA hardware was detected, but PyTorch could not use CUDA.
echo Falling back to the CPU profile.
uv sync --locked --no-dev --extra cpu
if errorlevel 1 goto :failure

uv run --no-dev --extra cpu python -c "import torch, onnxruntime as ort; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('ONNX providers:', ', '.join(ort.get_available_providers()))"
if errorlevel 1 goto :failure

set "MUSEFY_INSTALL_PROFILE=cpu"

:success
echo.
echo Musefy environment is ready with the %MUSEFY_INSTALL_PROFILE% profile.
echo You can now run: .venv\Scripts\python.exe -m app.desktop
exit /b 0

:failure
echo [ERROR] Musefy environment verification failed.
exit /b 1
