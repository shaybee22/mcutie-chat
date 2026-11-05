# Mcutie Chat for Linux 🐧💬🔐

**Portable Encrypted Group Chat over MQTT**
By James Powell (aka shaybee22)

Mcutie Chat (formerly MQChat) is a cross-platform, end-to-end encrypted group chat client that uses MQTT as the relay server. This version is built for Linux systems and can be compiled into a single, portable executable using PyInstaller—no Python installation required on the target machine!

> ⚠️ This desktop client still uses the old Fernet message format and can't talk to the current Android app until it's ported. See the [compatibility note](../README.md).

---

## 🚀 Features

* 🧠 Fully GUI-based (Tkinter)
* 🔐 End-to-end encryption using Fernet (AES)
* 🧵 Real-time group chat via MQTT broker
* 💾 Saved room configs with encryption
* 📥 Import/export rooms
* 👥 Online presence tracking
* ✅ Anonymous or authenticated MQTT login

---

## 📦 Requirements (to build)

* Python 3 with Tk (`sudo apt install python3-tk` on Debian/Ubuntu)
* pip
* The packages `paho-mqtt cryptography qrcode pillow certifi` (the build script installs them, plus PyInstaller)

The desktop client is a single file, `mqchat.py` at the repo root, shared by Windows and Linux. Its protocol code (encryption, QR codes, TLS) comes from `AndroidApp/`, the same code the Android app uses.

---

## 🛠 Build Instructions (Linux)

### 🔧 One-Click Build:

Use the included `build_mqchat.sh` script (best inside a virtualenv, since it installs packages with `pip3`):

```bash
./Linux/build_mqchat.sh
```

This will:

* Install PyInstaller and the app's packages
* Clean previous builds
* Compile `../mqchat.py` (with the shared modules from `../AndroidApp`) into a standalone executable
* Output it in `Linux/portable/`

Once complete, you’ll have a single binary file named `McutieChat` that can be copied to other Linux systems.

### Manual Build:

```bash
cd Linux
pip3 install pyinstaller paho-mqtt cryptography qrcode pillow certifi
pyinstaller --onefile --windowed --name="McutieChat" --paths ../AndroidApp --add-data "../mcutie-icon.png:." --distpath="./portable" ../mqchat.py
```

---

## 🧪 Running the App

Once built, run it like so:

```bash
./Linux/portable/McutieChat
```

You can also run it directly from Python, from the repo root (if you don't need portability):

```bash
pip3 install paho-mqtt cryptography qrcode pillow certifi
python3 mqchat.py
```

---

## 📁 File Overview

```
📁 mcutie-chat/
├── mqchat.py                  # The desktop client (Windows and Linux)
├── AndroidApp/                # Android app + the shared protocol modules
└── Linux/
    ├── build_mqchat.sh        # Builds the Linux executable from ../mqchat.py
    └── portable/              # Output folder for the standalone binary (created at build)
```

---

## 📝 License

MIT Non-Commercial License – Personal use only. Commercial use or resale requires permission. Full credit required for forks/derivatives. See [LICENSE](../LICENSE) for full terms.

---

## 🙋‍♂️ Author

**James Powell** (shaybee22)
Check out the full project and other platform versions at:
[https://github.com/shaybee22/mcutie-chat](https://github.com/shaybee22/mcutie-chat)

If you enjoy it, give it a ⭐ and share it with fellow Linux geeks!

---

Stay encrypted. Stay private. Stay chatty. 🔐💬🐧
