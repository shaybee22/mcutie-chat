@echo off
rem Builds the desktop client (mqchat.py) into a single Windows executable.
cd /d "%~dp0"
echo ========================================
echo    Mcutie Chat Portable Executable Builder
echo    By James Powell
echo ========================================
echo.

echo [1/4] Installing PyInstaller and the app's packages...
pip install pyinstaller paho-mqtt cryptography qrcode pillow certifi keyring
if %errorlevel% neq 0 (
    echo ERROR: Failed to install PyInstaller
    pause
    exit /b 1
)

echo.
echo [2/4] Cleaning previous builds...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "mqchat.spec" del "mqchat.spec"

echo.
echo [3/4] Building portable executable...
echo This may take a few minutes...
rem --paths: the protocol modules (chat_crypto, qr_exchange, tls_config) are shared with the Android app
rem keyring finds its backends via entry points; PyInstaller's keyring/win32ctypes hooks bundle them,
rem and the Windows Credential Manager backend plus win32ctypes' ctypes layer (loaded dynamically) are named explicitly
pyinstaller --onefile --windowed --name="McutieChat" --paths AndroidApp --hidden-import keyring.backends.Windows --collect-submodules win32ctypes.core.ctypes --copy-metadata keyring --icon=mcutie-icon.ico --add-data "mcutie-icon.ico;." --add-data "mcutie-icon.png;." --distpath="./portable" mqchat.py

if %errorlevel% neq 0 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo.
echo [4/4] Cleaning up build files...
rmdir /s /q "build"
del "McutieChat.spec"

echo.
echo ========================================
echo    SUCCESS! 
echo ========================================
echo.
echo Your portable McutieChat.exe is ready in the 'portable' folder!
echo.
echo File size: 
for %%I in (portable\McutieChat.exe) do echo %%~zI bytes (approx %%~zI bytes)
echo.
echo USAGE:
echo - Copy McutieChat.exe to any computer (no Python needed!)
echo - Run from USB stick, desktop, network drive
echo - No installation required
echo - No traces left behind
echo.
echo Ready to distribute! 🚀
echo.
pause