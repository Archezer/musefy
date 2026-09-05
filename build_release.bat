@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Musefy release build

echo Building CPU and CUDA installers plus the one-file profile selector...
echo This can take a long time and requires several gigabytes of free disk space.
echo.

if "%~1"=="" (
    set "MUSEFY_RELEASE_TAG=v1.0.0"
) else (
    set "MUSEFY_RELEASE_TAG=%~1"
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv was not found. Run install_musefy.bat first.
    pause
    exit /b 1
)

set "MUSEFY_RELEASE_TAG=%MUSEFY_RELEASE_TAG%"
if /I "%~2"=="--package-existing" (
    ".venv\Scripts\python.exe" "scripts\build_release.py" "%MUSEFY_RELEASE_TAG%" --package-existing
) else (
    ".venv\Scripts\python.exe" "scripts\build_release.py" "%MUSEFY_RELEASE_TAG%"
)
if errorlevel 1 (
    echo.
    echo [ERROR] Release build failed.
    pause
    exit /b 1
)

echo.
echo Release files are ready in dist\
pause
endlocal
