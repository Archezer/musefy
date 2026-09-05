@echo off
setlocal
cd /d "%~dp0"

echo Building Musefy...
call "%~dp0install_musefy.bat"
if errorlevel 1 (
    echo.
    echo [ERROR] Musefy environment preparation failed.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "scripts\build_musefy.py"

if errorlevel 1 (
    echo.
    echo [ERROR] Musefy build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\Musefy\Musefy.exe
echo This folder contains the complete portable application.
pause
endlocal
