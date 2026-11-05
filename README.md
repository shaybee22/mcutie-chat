# Mcutie Chat 💬🔒

**Encrypted Group Chat over MQTT**
Created by James Powell

Mcutie Chat (formerly MQChat / MQTT Chat) is a lightweight, secure group chat application that uses MQTT as its message relay protocol. Designed for privacy and simplicity, it features end-to-end encryption, room presets, presence tracking, and a GUI-friendly interface built with Python and Tkinter.

> ⚠️ **Compatibility: the desktop and Android clients can't talk to each other right now.**
> The desktop client (`mqchat.py`, `Linux/mqchat.py`) still uses the old **Fernet** message format. The Android app now uses **AES-256-GCM** with a new key format ([AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md)), so the two **cannot read each other's messages until the desktop client is ported**.
> Porting the desktop client (AES-256-GCM, plus Room/Key QR import by paste or file) is the next step. **There is no release yet:** one comes once both clients interoperate.

---

## 🧠 Key Features

* 🔐 End-to-end encrypted messages (desktop: Fernet; Android: AES-256-GCM, see the compatibility note above)
* 🌐 MQTT-based real-time message relay
* 👤 Presence tracking (online/offline status)
* 💾 Save and load favorite chat rooms
* 📋 GUI with tabs for Connection, Chat, and Room Management
* 🛠️ Support for MQTT authentication (optional)
* 🚀 Quick Connect and saved room profiles
* 📥 Import/Export chat room configurations
* ✅ Compatible with anonymous or authenticated MQTT brokers

---

## 🖥️ Desktop App (Python)

### 🛠 Requirements

* Python 3.x
* `paho-mqtt`
* `cryptography`
* `tkinter` (included with most Python installations)

### 📦 Installation

1. Clone the repo:

   ```bash
   git clone https://github.com/shaybee22/mcutie-chat.git
   cd mcutie-chat
   ```

2. Install dependencies:

   ```bash
   pip install paho-mqtt cryptography
   ```

3. Run the app:

   ```bash
   python mqchat.py
   ```

[View the code on GitHub](https://github.com/shaybee22/mcutie-chat/blob/main/mqchat.py)

---

## 📦 Creating a Portable Windows Executable

You can generate a self-contained `.exe` using `pyinstaller` and the included batch script.

### 🔧 One-click Build (Windows)

1. Install [PyInstaller](https://pyinstaller.org/):

   ```bash
   pip install pyinstaller
   ```

2. Run the batch script:

   ```bash
   build_mqchat.bat
   ```

This will compile `mqchat.py` into a portable `McutieChat.exe` inside the `portable/` folder.

[View the batch script](https://github.com/shaybee22/mcutie-chat/blob/main/build_mqchat.bat)

---

## 🖧 Run Your Own Broker

On a fresh Ubuntu server:

```bash
git clone https://github.com/shaybee22/mcutie-chat && cd mcutie-chat && sudo ./install.sh
```

It installs mosquitto with password logins, optional TLS (Let's Encrypt or a self-signed CA) and a firewall, tests it, and prints the settings to enter in the app. See [BROKER-SETUP.md](BROKER-SETUP.md).

---

## 📱 Android Version

An Android version of Mcutie Chat is available! It's written using Kivy and Buildozer for packaging. It has AES-256-GCM messages, in-person QR key/room exchange, and TLS to the broker (see [AndroidApp/README.md](AndroidApp/README.md)).

📂 [View the Android App on GitHub](https://github.com/shaybee22/mcutie-chat/tree/main/AndroidApp)

Inside the AndroidApp folder, you'll find installation and build instructions using **Buildozer**.

---

## 📁 File Structure

```
📁 mcutie-chat/
├── mqchat.py                 # Main Python desktop app
├── build_mqchat.bat          # Batch script to create Windows .exe
├── Linux/                    # Linux desktop version + build script
├── mqtt_chat_rooms.json      # Encrypted saved room profiles (created at runtime)
├── AndroidApp/               # Android version using Kivy/Buildozer
├── LICENSE                   # Custom MIT Non-Commercial License
└── README.md                 # You're reading it!
```

---

## 🔒 Security Note

The desktop client uses **Fernet encryption** (AES-128 in CBC mode with HMAC for integrity). The Android app uses **AES-256-GCM** with generated 256-bit keys or scrypt-derived passphrases, and supports TLS to the broker. See [AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md). The two formats are not compatible yet. Only users with the same shared encryption key can read each other's messages. Never share your key over insecure channels!

---

## 🔧 Roadmap

* [ ] **Next:** port the desktop client to AES-256-GCM + Room/Key QR import (paste/load), then the first release
* [ ] Add file/image sharing
* [ ] Push notifications
* [ ] Android/Desktop cross-device syncing
* [ ] Encrypted voice calls (stretch goal)

---

## 📜 License

This project is licensed under the [MIT Non-Commercial License](https://github.com/shaybee22/mcutie-chat/blob/main/LICENSE) — free for personal use, credit required for modifications, and written permission required for commercial or resale purposes. 🥥🌴😉

---

## 🙋‍♂️ Author

**James Powell** (a.k.a. shaybee22)
If you enjoy this project, consider giving it a ⭐ on [GitHub](https://github.com/shaybee22/mcutie-chat)! 💙

