@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo  Barcode_Merger Build Script
echo ============================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3 and add it to PATH.
    pause
    exit /b 1
)

echo [1/4] Python version check passed.
python --version
echo.

REM Upgrade pip
echo [2/4] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)
echo.

REM Install requirements
echo [3/4] Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.

REM Clean old build files
echo [4/4] Building executable...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist *.spec del *.spec 2>nul

REM Build the executable
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name Barcode_Merger ^
    --manifest app.manifest ^
    barcode_merger_gui.py

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo Build completed successfully!
echo Executable location: dist\Barcode_Merger.exe
echo ============================================
pause
