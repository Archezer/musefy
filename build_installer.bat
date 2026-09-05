@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Musefy installer build

echo Preparing the selected Python runtime...
call "%~dp0install_musefy.bat"
if errorlevel 1 (
    echo.
    echo [ERROR] Musefy environment preparation failed.
    pause
    exit /b 1
)

echo.
echo Building the complete Musefy application bundle...
".venv\Scripts\python.exe" "scripts\build_musefy.py"
if errorlevel 1 (
    echo.
    echo [ERROR] Musefy application build failed.
    pause
    exit /b 1
)

set "ISCC_EXE="
for %%P in ("C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "C:\Program Files\Inno Setup 6\ISCC.exe") do (
    if exist "%%~P" set "ISCC_EXE=%%~P"
)
if not defined ISCC_EXE (
    for /f "delims=" %%P in ('where ISCC.exe 2^>nul') do if not defined ISCC_EXE set "ISCC_EXE=%%P"
)

if not defined ISCC_EXE (
    echo.
    echo [ERROR] Inno Setup 6 was not found.
    echo Install Inno Setup 6 and run this file again.
    echo Download: https://jrsoftware.org/isinfo.php
    pause
    exit /b 1
)

echo.
echo Creating the Windows installer...
"%ISCC_EXE%" "installer\Musefy.iss"
if errorlevel 1 (
    echo.
    echo [ERROR] Installer creation failed.
    pause
    exit /b 1
)

echo.
echo Installer ready: dist\Musefy-Setup.exe
pause
endlocal
