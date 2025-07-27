# 📱 MQTTChat – Android Version (Buildozer)

Welcome to the **Android Kivy version** of [MQTTChat](https://github.com/shaybee22/MQTTChat/), a fully encrypted MQTT-based group chat app! This version is optimized for mobile devices using **Kivy** and **Buildozer**, and supports encrypted messaging and presence updates just like the desktop counterpart.

---

## 🚀 Features

* 🛡️ End-to-end encrypted group messaging
* 🌐 MQTT broker integration
* 👥 Online user presence detection
* 🔐 Password-derived encryption key (Fernet/AES)
* 📱 Kivy GUI for mobile touch screens
* 💬 Smooth chat interface with real-time updates

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
git clone https://github.com/shaybee22/MQTTChat.git
cd MQTTChat/AndroidApp
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
```

---

## 🔐 Encryption Details

* Encryption uses **Fernet** (AES-128-CBC + HMAC)
* Messages are encrypted client-side before sending
* A shared password-derived key is used for room-wide secure chat

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

See [LICENSE](https://github.com/shaybee22/MQTTChat/blob/main/LICENSE) for usage restrictions. TL;DR: **Personal use only**, give full credit if modified, and **don’t sell it** without permission.

---
**Future Features!**
Adding qr code for easy encryption key sharing on the Android App!
Added qr code for encryption key for sharing key in person at 10:00 PM 7/26/2025

