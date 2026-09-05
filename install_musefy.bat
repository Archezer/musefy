@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "MUSEFY_ROOT=%CD%"

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
echo [5/6] Downloading required models and local MERT snapshot...
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The project environment was not created.
    exit /b 1
)
".venv\Scripts\python.exe" "scripts\download_models.py"
if errorlevel 1 (
    echo [ERROR] Model installation failed.
    exit /b 1
)

echo [6/7] Building the Musefy Windows launcher...
call :build_source_launcher
if errorlevel 1 (
    echo [WARNING] Native launcher could not be built.
    echo Falling back to the windowed Python launcher.
)

echo [7/7] Creating Start Menu and desktop shortcuts...
call :create_shortcuts
if errorlevel 1 (
    echo [WARNING] Could not create shortcuts automatically.
    echo The application is still installed and can be started manually.
)

echo.
echo Musefy is ready with the %MUSEFY_INSTALL_PROFILE% profile.
echo Start Musefy from the Start Menu or the desktop shortcut.
echo Right-click the shortcut and choose "Pin to taskbar" if desired.
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

:create_shortcuts
if "%MUSEFY_LAUNCHER%"=="1" (
    "%MUSEFY_ROOT%\Musefy.exe" --create-shortcuts
    exit /b %errorlevel%
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; $root = $env:MUSEFY_ROOT; if ($env:MUSEFY_LAUNCHER -eq '1') { $target = Join-Path $root 'Musefy.exe'; $arguments = '' } else { $target = Join-Path $root '.venv\Scripts\pythonw.exe'; $arguments = '-m app.desktop' }; if (-not (Test-Path $target)) { throw 'Musefy launcher was not found.' }; $icon = Join-Path $root 'assets\musefy-mark.ico'; $shell = New-Object -ComObject WScript.Shell; $locations = @((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Musefy.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Musefy.lnk')); foreach ($location in $locations) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $location) | Out-Null; $shortcut = $shell.CreateShortcut($location); $shortcut.TargetPath = $target; $shortcut.Arguments = $arguments; $shortcut.WorkingDirectory = $root; if (Test-Path $icon) { $shortcut.IconLocation = $icon }; $shortcut.Save() }"
exit /b %errorlevel%

:build_source_launcher
set "MUSEFY_LAUNCHER="
set "MUSEFY_CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%MUSEFY_CSC%" set "MUSEFY_CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%MUSEFY_CSC%" exit /b 1
if not exist "%MUSEFY_ROOT%\launcher\MusefyLauncher.cs" exit /b 1
if not exist "%MUSEFY_ROOT%\assets\musefy-mark.ico" exit /b 1

"%MUSEFY_CSC%" /nologo /target:winexe /platform:x64 /optimize+ /r:System.Windows.Forms.dll /r:Microsoft.CSharp.dll /out:"%MUSEFY_ROOT%\Musefy.exe" /win32icon:"%MUSEFY_ROOT%\assets\musefy-mark.ico" "%MUSEFY_ROOT%\launcher\MusefyLauncher.cs"
if errorlevel 1 exit /b 1
set "MUSEFY_LAUNCHER=1"
exit /b 0

:failure
echo [ERROR] Musefy environment verification failed.
exit /b 1
