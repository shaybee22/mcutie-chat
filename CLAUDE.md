# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

MQTT Chat: a Kivy mobile (Android-targeted) client for end-to-end encrypted group chat over an MQTT broker. It is a port of a separate "desktop version" (not in this repo) and must stay wire-compatible with it — many comments say "same as desktop" for that reason. There are no tests, linter config, or README.

## Commands

```bash
# Run locally (desktop window)
pip install kivy paho-mqtt cryptography qrcode pillow
python main.py

# Run just the connection screen standalone (has its own __main__ test app)
python connection_screen.py

# Crypto self-test (needs only `cryptography`; prints the PROTOCOL.md test vectors)
python3 chat_crypto.py

# Build Android APK (config in buildozer.spec); output: bin/mqttchat-0.3-arm64-v8a-debug.apk
source ~/.venvs/buildozer/bin/activate          # must be activated (VIRTUAL_ENV set), not just on PATH
export PATH="$HOME/.cargo/bin:$PATH"            # rustup/cargo: p4a builds cryptography from source
export PIP_NO_BINARY=charset-normalizer         # see the comment above `requirements` in buildozer.spec
yes | buildozer android debug                   # `yes` accepts the SDK licences on first run

# Install and launch on the USB-attached phone (WSL's /usr/bin/adb sees it)
adb install -r bin/mqttchat-0.3-arm64-v8a-debug.apk
adb shell monkey -p org.example.mqttchat -c android.intent.category.LAUNCHER 1
adb logcat -s python:* SDL:* AndroidRuntime:*

# Headless test peer (venv: ~/.venvs/mqttpeer with paho-mqtt 2.1.0 + cryptography)
CHAT_KEY=... MQTT_PASSWORD=... ~/.venvs/mqttpeer/bin/python tools/test_peer.py \
    --host BROKER --room ROOM --mqtt-user USER --send "hello" --duration 60
```

Build quirks (all with p4a master + Python 3.14 host, Oct 2026):
- `kivy` is pinned to 2.3.1 because p4a's kivy recipe patches that release; `kivy==master` fails at patching.
- arm64-v8a only: `cryptography` fails to build for armeabi-v7a (p4a passes host x86_64 Python headers → `LONG_BIT` error).
- If the build fails with `ImportError: cannot import name 'BuildDependencyInstallError'`, p4a's cached build venv has a half-upgraded pip: `rm -rf .buildozer/android/platform/build-arm64-v8a/build/venv`.

A local broker (e.g. `mosquitto` on `localhost:1883`, the UI defaults) is needed to exercise the chat flow.

`main.py` uses `mqtt.CallbackAPIVersion.VERSION1`, which needs paho-mqtt 2.x; keep the `buildozer.spec` pin on 2.x.

`connection_screen.py` and `buildozer.spec` use CRLF line endings; the other files use LF. Preserve them when editing (scripted rewrites in text mode silently convert CRLF to LF).

## Architecture

Four modules, no `.kv` files — all UI is built in Python in `__init__`.

- `main.py` — `MQTTChatApp` owns all networking, encryption, and presence state, plus the `ScreenManager` with two screens (`'connection'`, `'chat'`). Screens never talk to MQTT directly; they call back into the app (`connect_to_mqtt`, `send_message`, `switch_to_connection`).
- `connection_screen.py` — form for username/broker/room/MQTT auth/encryption key; saved-room profiles; key generation, clipboard copy, and QR display.
- `chat_crypto.py` — all key handling and message encrypt/decrypt (no Kivy imports). `main.py` and `connection_screen.py` call into it.
- `chat_screen.py` — renders messages into a single markup `Label` inside a `ScrollView`; the app pushes updates via `add_chat_message`, `add_system_message`, `update_users_list`.

### Threading

paho callbacks (`on_mqtt_connect`, `on_mqtt_message`, ...) run on paho's network thread (`loop_start()`), and heartbeat/cleanup use `threading.Timer`. Any UI change from these must go through `Clock.schedule_once(...)`. Disconnect runs in a daemon thread and finishes on the UI thread via `_finish_disconnect`.

### Wire protocol

`PROTOCOL.md` is the spec (topics, presence, AES-256-GCM payload, key rules, test vectors). Any change to `chat_crypto.py` or topic/payload handling must update `PROTOCOL.md`, because the separate desktop client (not in this repo) is ported from it. In brief:
- topics `chat/<room>/messages` and retained, unencrypted `chat/<room>/presence/<username>`;
- payload = `base64(0x01 || 12-byte nonce || AES-256-GCM ciphertext+tag)`, with the messages topic as AAD;
- a 44-char base64url key is used raw, anything else goes through scrypt with a room-derived salt.

Own messages are rendered locally on send; incoming messages from the same username are dropped to avoid duplicates.

### Persistence

Saved rooms are JSON files in `rooms/` relative to the working directory (created at import time of `connection_screen.py`). They store the encryption key and MQTT password in plaintext.

## Current status (paused 2026-10-11)

The work is split into four phases (1: AES-256-GCM crypto, 2: TLS, 3: QR export, 4: QR camera import). Do one phase at a time and stop after each so the user can test. Use plan mode before editing, and keep changes surgical. The desktop client is deferred: change only the mobile app, and keep `PROTOCOL.md` exact so it can be ported later.

**Done (Phase 1, code complete):**
- `chat_crypto.py` provides AES-256-GCM with a version byte and a random 96-bit nonce. A generated 256-bit key is used raw; a passphrase goes through scrypt with a room-derived salt. Fernet and the SHA-256 `derive_key` are gone.
- `main.py` and `connection_screen.py` call into it. `PROTOCOL.md` documents the format, with test vectors.
- `tools/test_peer.py` is a headless peer that joins a room and sends and receives messages.
- `buildozer.spec` builds: paho-mqtt 2.1.0, kivy 2.3.1, arm64 only, `tools/` excluded, charset_normalizer workaround.

**Tested:**
- `python3 chat_crypto.py`: the self-test passes, and the PROTOCOL.md test vector decrypts.
- All modules compile.
- The debug APK builds successfully, and its app code (`chat_crypto`, `main`) is in the bundle.

**NOT tested yet:**
- The APK has never been installed or launched on the phone, and logcat has not been checked.
- Connect, and two-way messaging between the phone and `tools/test_peer.py` against a live broker. The user's broker on port 1883 was unreachable from WSL, Windows and the phone: the host answers SSH, but MQTT ports time out.
- The test peer has not completed a run, because its only attempt timed out on that broker.
- The desktop app has not been run with Kivy. Kivy is not installed in WSL.

**Known issue (not fixed):** the APK bundles `chardet` 7.6.0 (a Kivy → requests dependency) as x86_64 `.so` files, which can't load on ARM. The app doesn't import `chardet` or `requests`, so it probably doesn't matter yet, but check logcat for it. The fix is the same pure-Python approach used for charset_normalizer.

**Next steps to resume:**
1. Confirm that the broker is reachable: `timeout 5 bash -c 'echo > /dev/tcp/<broker>/1883'`.
   - If the broker can't be fixed, run a local broker in WSL and use `adb reverse tcp:1883 tcp:1883`. The phone then connects to `localhost:1883`.
2. Build the APK (commands above), then `adb install -r`, launch it, and watch logcat. Fix any startup errors and repeat.
3. To avoid typing the key on the phone, push a saved-room JSON file into the app's `rooms/` directory with `adb shell run-as org.example.mqttchat` (the debug APK is debuggable). The user then picks it from Load Room.
4. Run `tools/test_peer.py` in the same room. Confirm that phone → peer and peer → phone both work, using the peer's output and logcat. The user watches with MQTT Explorer.
5. Report the results and stop. Start Phase 2 (TLS) only when the user says so.
