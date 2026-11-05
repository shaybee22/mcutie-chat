# Mcutie Chat 💬🔒

**Encrypted Group Chat over MQTT**
Created by James Powell

Mcutie Chat (formerly MQChat / MQTT Chat) is a lightweight, secure group chat application that uses MQTT as its message relay protocol. Designed for privacy and simplicity, it features end-to-end encryption, room presets, presence tracking, and a GUI-friendly interface built with Python and Tkinter.

> ✅ **The desktop client and the Android app talk to each other.** Both speak Mcutie Chat protocol v1 ([AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md)): AES-256-GCM messages, in-person Room/Key QR exchange, and optional TLS to the broker.
> Clients from before protocol v1 (the old Fernet format) can't read v1 messages, so update every device in a room. **No release yet.**

---

## 🧠 Key Features

* 🔐 End-to-end encrypted messages (AES-256-GCM), the same on desktop and Android
* 📷 Share a room in person with a Room QR or Key QR, checked with a read-aloud fingerprint
* 🔒 Optional TLS to the broker (pinned CA for self-signed brokers, or public CAs)
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
* `paho-mqtt`, `cryptography`, `qrcode`, `pillow`, `certifi`
* `tkinter` (included with most Python installations; `python3-tk` on Debian/Ubuntu)

The desktop client is one file, `mqchat.py`, for Windows and Linux. Its protocol code is shared with the Android app (`AndroidApp/`), so keep the repo together.

### 📦 Installation

1. Clone the repo:

   ```bash
   git clone https://github.com/shaybee22/mcutie-chat.git
   cd mcutie-chat
   ```

2. Install dependencies:

   ```bash
   pip install paho-mqtt cryptography qrcode pillow certifi
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

Both clients use **AES-256-GCM** with generated 256-bit keys or scrypt-derived passphrases, and support TLS to the broker (see [AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md)). Only users with the same room key can read each other's messages. Share keys in person (Room/Key QR) and compare the fingerprint, never over insecure channels.

- The Android app blocks screenshots while a QR is shown; desktops can't, so close the QR window when you're done.
- The desktop client's saved-rooms file (`mqtt_chat_rooms.json`) is obfuscated with a key built into the code, **not** protected: anyone with access to that file can read the room keys and broker passwords. Keep it private.

---

## 🔧 Roadmap

* [x] Desktop client on protocol v1 (AES-256-GCM, QR exchange, TLS)
* [ ] First release
* [ ] Protect the desktop saved-rooms file properly (OS keyring)
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

