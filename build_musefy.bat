@echo off
setlocal
cd /d "%~dp0"

echo Building Musefy...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\build_musefy.py"
) else (
    where uv >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Neither .venv nor uv was found.
        echo Create the project environment first, then run this file again.
        pause
        exit /b 1
    )
    uv run python "scripts\build_musefy.py"
)

if errorlevel 1 (
    echo.
    echo [ERROR] Musefy build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\Musefy\Musefy.exe
pause
endlocal
