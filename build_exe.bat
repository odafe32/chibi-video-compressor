@echo off
REM Run this on Windows, inside this folder, with Python 3.10+ installed.
REM It creates a virtual environment, installs dependencies, and builds
REM a single self-contained dist\Chibi.exe with ffmpeg/ffprobe
REM embedded inside it.

setlocal
cd /d "%~dp0"

if not exist "bin\ffmpeg.exe" (
    echo.
    echo [ERROR] bin\ffmpeg.exe not found.
    echo Download a Windows ffmpeg build from https://www.gyan.dev/ffmpeg/builds/
    echo ^(the "release essentials" zip^), copy ffmpeg.exe and ffprobe.exe from its
    echo bin\ folder into THIS project's bin\ folder, then re-run this script.
    echo.
    pause
    exit /b 1
)
if not exist "bin\ffprobe.exe" (
    echo [ERROR] bin\ffprobe.exe not found. See message above.
    pause
    exit /b 1
)

if not exist "assets\Chibi.ico" (
    echo.
    echo [ERROR] assets\Chibi.ico not found.
    echo Make sure the assets\ folder ^(Chibi.ico and the
    echo PNGs^) has been copied into this project folder, next to
    echo gui_app.py, before running this script.
    echo.
    pause
    exit /b 1
)

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip >nul
pip install -r requirements.txt

echo Building Chibi.exe (embedding ffmpeg + ffprobe + icon)...
pyinstaller --noconfirm --onefile --windowed --name Chibi ^
    --icon "assets\Chibi.ico" ^
    --add-binary "bin\ffmpeg.exe;." ^
    --add-binary "bin\ffprobe.exe;." ^
    --add-data "assets\Chibi_256.png;assets" ^
    --add-data "assets\Chibi.ico;assets" ^
    gui_app.py

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed - see the messages above for the real cause.
    echo dist\Chibi.exe was NOT created.
    pause
    exit /b 1
)

if not exist "dist\Chibi.exe" (
    echo.
    echo [ERROR] Build reported success but dist\Chibi.exe is missing.
    pause
    exit /b 1
)

echo.
echo Build complete. Find the exe at: dist\Chibi.exe
echo It is fully self-contained - ffmpeg and ffprobe are embedded, no extra files needed.
pause
