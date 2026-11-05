# 📱 Mcutie Chat – Android Version (Buildozer)

Welcome to the **Android Kivy version** of [Mcutie Chat](https://github.com/shaybee22/mcutie-chat/), a fully encrypted MQTT-based group chat app, optimized for mobile devices using **Kivy** and **Buildozer**.

> ✅ **The desktop client and the Android app talk to each other.** Both speak Mcutie Chat protocol v1 ([AndroidApp/PROTOCOL.md](PROTOCOL.md)): AES-256-GCM messages, in-person Room/Key QR exchange, and optional TLS to the broker.
> Clients from before protocol v1 (the old Fernet format) can't read v1 messages, so update every device in a room. **No release yet.**

---

## 🚀 Features

* 🛡️ End-to-end encrypted group messaging
* 🌐 MQTT broker integration
* 👥 Online user presence detection
* 🔐 AES-256-GCM messages: generated 256-bit keys, or passphrases stretched with scrypt
* 📱 Kivy GUI for mobile touch screens
* 💬 Smooth chat interface with real-time updates
* 📷 In-person QR exchange: **Key QR** (room key) and **Room QR** (full room setup, so a new user joins with one scan), with a read-aloud fingerprint; screenshots blocked while a QR is shown
* 🔒 TLS to the broker, with a pinned CA certificate (self-signed brokers) or public CAs (e.g. Let's Encrypt)

---

## 📦 Requirements

Make sure you’re on **Linux** and have:

* Python 3.9+
* Buildozer
* Cython
* `cryptography`, `paho-mqtt`, and `kivy`

You can install them using:

```bash
pip install cython kivy paho-mqtt cryptography
```

---

## 🧰 Build Instructions (using Buildozer)

1. **Clone the repo** (if you haven’t already):

```bash
git clone https://github.com/shaybee22/mcutie-chat.git
cd mcutie-chat/AndroidApp
```

2. **Install Buildozer**:

```bash
pip install buildozer
```

3. **Initialize build files** (if not already done):

```bash
buildozer init
```

> ✅ This project already includes a pre-configured `buildozer.spec` file!

> ℹ️ The exact, tested build steps and build-environment quirks (Python 3.14 host, python-for-android workarounds) are in [CLAUDE.md](CLAUDE.md).

4. **Build the APK**:

```bash
buildozer -v android debug
```

> 🛠️ The first build may take a while as it downloads the Android SDK/NDK.

5. **Install the APK on a device**:

```bash
buildozer android deploy run
```

---

## 📂 Project Structure

```
AndroidApp/
├── main.py                  # Main Kivy App
├── chat_screen.py          # Chat screen interface
├── connection_screen.py    # Connection & login screen
├── buildozer.spec          # Android build configuration
├── chat_crypto.py          # AES-256-GCM, key derivation, fingerprint
├── qr_exchange.py          # Room/Key QR payloads
├── android_qr.py           # QR scanner (ZXing) + screenshot blocking
├── tls_config.py           # TLS trust rules
├── p4a-recipes/            # python-for-android recipe fix (cryptography)
├── tools/test_peer.py      # Headless test client
└── PROTOCOL.md             # Wire format spec (messages, QR codes, TLS)
```

---

## 🔐 Encryption Details

* Messages use **AES-256-GCM** with a random nonce per message, bound to the room's topic
* Room keys are either generated (random 256-bit) or derived from a passphrase with **scrypt** (room-specific salt)
* Messages are encrypted client-side before sending; the broker only sees ciphertext
* Full specification: [PROTOCOL.md](PROTOCOL.md)

---

## 📸 Screenshots (optional)

> Comming soon!

---

## ⚠️ Note

Ensure that the MQTT broker you're connecting to:

* Supports WebSockets (for browser builds, if future expansion)
* Has appropriate topics and authentication enabled (or anonymous access)

---

## 📄 License

See [LICENSE](https://github.com/shaybee22/mcutie-chat/blob/main/LICENSE) for usage restrictions. TL;DR: **Personal use only**, give full credit if modified, and **don’t sell it** without permission.

---
**Future Features!**
Adding qr code for easy encryption key sharing on the Android App!

Added qr code for encryption key for sharing key in person at 10:00 PM 7/26/2025

