# Mcutie Chat 💬🔒

**End-to-end encrypted group chat over your own MQTT broker.**
By James Powell (shaybee22)

Mcutie Chat is a small group chat for people who want to run it themselves. Messages travel through an ordinary [MQTT](https://mqtt.org/) broker, for example [Mosquitto](https://mosquitto.org/) on a cheap VPS, but they're encrypted on your device. The broker only ever sees ciphertext. There are no accounts and no central server: a room is just a name plus a key that everyone in it shares.

There are two clients, and they talk to each other:
- **Android app** (Kivy), with a camera QR scanner;
- **Desktop client** (Python/Tkinter) for Windows and Linux.

**Latest release: [v1.1.0](https://github.com/shaybee22/mcutie-chat/releases/tag/v1.1.0)**

---

## ⬇️ Download

| Platform | File | Notes |
|---|---|---|
| Android 11+ (64-bit ARM) | [mcutiechat-1.1.0-arm64-v8a-release.apk](https://github.com/shaybee22/mcutie-chat/releases/download/v1.1.0/mcutiechat-1.1.0-arm64-v8a-release.apk) | Needs Android 11 or later. Allow installs from unknown sources. **Updating from v1.0.0:** your saved rooms are lost once, so have your Room QRs ready to re-scan; later updates keep them. If you had a test build installed before, uninstall it first: the signing key is different. Uninstalling deletes that build's saved rooms. |
| Windows (64-bit) | Unchanged since v1.0.0: [McutieChat-1.0.0-windows-x64.exe](https://github.com/shaybee22/mcutie-chat/releases/download/v1.0.0/McutieChat-1.0.0-windows-x64.exe) | Portable: nothing to install, and no Python needed. It's unsigned, so SmartScreen may warn you ("More info → Run anyway"). |
| Linux | [run from source](#-running-from-source-linux) | Or build a single-file binary: see [Linux/README.md](Linux/README.md). |

Checksums are in `SHA256SUMS.txt` on each release page: [v1.1.0](https://github.com/shaybee22/mcutie-chat/releases/download/v1.1.0/SHA256SUMS.txt) for the Android APK, [v1.0.0](https://github.com/shaybee22/mcutie-chat/releases/download/v1.0.0/SHA256SUMS.txt) for the Windows exe.

You'll also need a broker. You can [host your own](#-hosting-your-own-broker) or use any MQTT broker you have access to.

---

## 🔐 How room encryption works

Every room has a **room key**, which you either:
- **generate**: a random 256-bit key (the **Generate** button), recommended; or
- **type in as a passphrase**: it's stretched with scrypt, salted with the room name. A weak passphrase is still weak, so prefer a generated key.

Every message is encrypted on the sending device with **AES-256-GCM**:
- each message gets a fresh random nonce;
- the room's topic is bound into the encryption, so a message can't be replayed into another room;
- anyone without the key, including the broker, sees only random-looking bytes. A tampered message is rejected, not shown.

Each key has a **fingerprint** like `273B-2CAF-623A-EBA8`. Two people who see the same fingerprint have the same key. Read it aloud to each other to check.

Optionally, the connection to the broker can use **TLS**, which also hides your broker password and the room names in transit. For a self-signed broker, a room can pin its own CA certificate. Without one, the app trusts the usual public CAs.

**What the broker can still see:**
- room names, because they're in the MQTT topics;
- display names and who is online, because presence messages are not encrypted;
- when messages are sent, and how big they are.

The full wire format is in [AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md).

---

## 📷 Sharing a room in person: QR codes

Never send room keys over email or another chat app. Show a QR code instead:

| QR | Contains | Use it for |
|---|---|---|
| **Key QR** | Room name + key | Someone who is already set up on the same broker |
| **Room QR** | Broker address, port, TLS setting and CA, MQTT login, room name + key | A new user: one scan and they only need to type their own name |

1. On the device that already has the room, press **Key QR** or **Room QR**.
2. On the other phone, press **Scan QR**. On a desktop, which can't scan, use **Import QR text...** and paste the QR's contents.
3. The receiver sees the fingerprint and must confirm the import. Compare fingerprints out loud.

The QR codes are designed to show only briefly:
- they're never saved to a file;
- they close after 60 seconds;
- on Android, screenshots are blocked while one is on screen. Desktops can't block screenshots, so close the window when you're done.

A Room QR contains your MQTT password, so treat it like the password itself.

---

## 🐧 Running from source (Linux)

You need Python 3 with Tk:

```bash
sudo apt install python3-tk python3-venv          # Debian/Ubuntu
git clone https://github.com/shaybee22/mcutie-chat.git
cd mcutie-chat
python3 -m venv .venv && . .venv/bin/activate
pip install paho-mqtt cryptography qrcode pillow certifi
python3 mqchat.py
```

The desktop client is the single file `mqchat.py`. It imports its encryption, QR and TLS code from `AndroidApp/`, the same code the Android app uses, so keep the repo together. The same steps work on Windows with `python mqchat.py`.

To build a portable binary yourself:
- **Linux:** follow [Linux/README.md](Linux/README.md).
- **Windows:** run `build_mqchat.bat` from a normal Windows folder. It can't be run from a `\\wsl.localhost\...` path. The result is `portable\McutieChat.exe`.

To build the Android app, see [AndroidApp/README.md](AndroidApp/README.md).

---

## 🖧 Hosting your own broker

On a fresh Ubuntu server (a VPS, droplet or VM):

```bash
git clone https://github.com/shaybee22/mcutie-chat && cd mcutie-chat && sudo ./install.sh
```

The installer:
- installs Mosquitto with password logins only (anonymous access is turned off);
- sets up TLS with **Let's Encrypt** (needs a domain), a **self-signed CA** (works with a bare IP), or no TLS;
- configures the firewall;
- tests the broker;
- prints the settings to type into the app.

Add more users later with `sudo ./install.sh --add-user`.

After that, set up one device by hand, and share the room with everyone else using a **Room QR**.

Details, all the options and troubleshooting: [BROKER-SETUP.md](BROKER-SETUP.md).

---

## 📚 More documentation

| | |
|---|---|
| [AndroidApp/README.md](AndroidApp/README.md) | Android app: features, building with Buildozer |
| [Linux/README.md](Linux/README.md) | Desktop client on Linux: building the portable binary |
| [BROKER-SETUP.md](BROKER-SETUP.md) | Self-hosted Mosquitto broker with `install.sh` |
| [AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md) | Wire protocol v1: topics, encryption, key rules, QR formats, TLS trust |

---

## ⚠️ Known limitations

- Clients from before protocol v1 (the old Fernet-based MQTT Chat) can't talk to v1. Update every device in a room.
- The desktop client's saved rooms (`mqtt_chat_rooms.json`, in the folder you start it from) are obfuscated, not encrypted. Anyone who can read that file can read your room keys and broker passwords, so keep it private. Proper protection through the OS keyring is on the roadmap.
- The Android QR scanner opens in landscape.
- Android saved rooms from v1.0.0 can't be carried over to v1.1.0 (the old version kept them where Android updates delete them). Re-scan your Room QRs after updating.

---

## 🔧 Roadmap

* [x] Protocol v1 on desktop and Android (AES-256-GCM, QR exchange, TLS)
* [x] First release (v1.0.0)
* [x] Android saved rooms encrypted, unlocked with fingerprint or PIN, and kept across updates (v1.1.0)
* [ ] Protect the desktop saved-rooms file properly (OS keyring)
* [ ] File/image sharing
* [ ] Push notifications
* [ ] Android/Desktop cross-device syncing
* [ ] Encrypted voice calls (stretch goal)

---

## 📜 License

[MIT Non-Commercial License](LICENSE): free for personal use, with credit required for modifications. Commercial use or resale needs written permission. 🥥🌴😉

## 🙋‍♂️ Author

**James Powell** (a.k.a. shaybee22). If you enjoy Mcutie Chat, give it a ⭐ on [GitHub](https://github.com/shaybee22/mcutie-chat)! 💙
