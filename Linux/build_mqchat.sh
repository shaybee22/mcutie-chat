#!/bin/bash
# Builds the shared desktop client (../mqchat.py) into a single Linux executable.
cd "$(dirname "$0")" || exit 1

echo "========================================"
echo "   Mcutie Chat Portable Executable Builder"
echo "   By James Powell"
echo "========================================"
echo

echo "[1/4] Installing PyInstaller and the app's packages..."
pip3 install pyinstaller paho-mqtt cryptography qrcode pillow certifi
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install PyInstaller"
    exit 1
fi

echo
echo "[2/4] Cleaning previous builds..."
rm -rf dist build mqchat.spec

echo
echo "[3/4] Building portable executable..."
echo "This may take a few minutes..."
# --paths: the protocol modules (chat_crypto, qr_exchange, tls_config) are shared with the Android app
pyinstaller --onefile --windowed --name="McutieChat" --paths ../AndroidApp --add-data "../mcutie-icon.png:." --distpath="./portable" ../mqchat.py

if [ $? -ne 0 ]; then
    echo "ERROR: Build failed!"
    exit 1
fi

echo
echo "[4/4] Cleaning up build files..."
rm -rf build McutieChat.spec

echo
echo "========================================"
echo "    SUCCESS!"
echo "========================================"
echo
echo "Your portable McutieChat executable is ready in the 'portable' folder!"
echo
echo "File size:"
ls -lh portable/McutieChat
echo
echo "USAGE:"
echo "- Copy McutieChat to any Linux computer (no Python needed!)"
echo "- Run from USB stick, home folder, network drive"
echo "- No installation required"
echo "- No traces left behind"
echo
echo "Ready to distribute! 🚀"
echo