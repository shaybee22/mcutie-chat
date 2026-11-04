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

# Self-tests (no Kivy needed): crypto + fingerprint test vectors, QR payload rules
python3 chat_crypto.py
python3 qr_exchange.py

# Build Android APK (config in buildozer.spec); output: bin/mqttchat-0.3-arm64-v8a-debug.apk
source ~/.venvs/buildozer/bin/activate          # must be activated (VIRTUAL_ENV set), not just on PATH
export PATH="$HOME/.cargo/bin:$PATH"            # rustup/cargo: p4a builds cryptography from source
export PIP_NO_BINARY=charset-normalizer         # see the comment above `requirements` in buildozer.spec
rm -rf .buildozer/android/platform/build-arm64-v8a/build/venv   # p4a corrupts this venv on every rebuild
yes | buildozer android debug                   # `yes` accepts the SDK licences on first run

# Install and launch on the phone. If WSL's `adb devices` is empty (phone attached to Windows,
# not via usbipd), use Windows' adb.exe with a Windows path: adb.exe install -r "$(wslpath -w bin/...apk)"
adb install -r bin/mqttchat-0.3-arm64-v8a-debug.apk
adb shell monkey -p org.example.mqttchat -c android.intent.category.LAUNCHER 1
adb logcat -s python:* SDL:* AndroidRuntime:*

# Run the app on the desktop (WSLg). Kivy 2.3.1 has no Python 3.14 wheels, so use the 3.12 venv
~/.venvs/mqttdesk/bin/python main.py

# Headless test peer (venv: ~/.venvs/mqttpeer with paho-mqtt 2.1.0 + cryptography)
CHAT_KEY=... MQTT_PASSWORD=... ~/.venvs/mqttpeer/bin/python tools/test_peer.py \
    --host BROKER --room ROOM --mqtt-user USER --send "hello" --duration 60
```

Build quirks (all with p4a master + Python 3.14 host, Oct 2026):
- `kivy` is pinned to 2.3.1 because p4a's kivy recipe patches that release; `kivy==master` fails at patching.
- arm64-v8a only: `cryptography` fails to build for armeabi-v7a (p4a passes host x86_64 Python headers → `LONG_BIT` error).
- p4a's build venv (`.buildozer/.../build/venv`) ends up with a half-upgraded pip on every rebuild (`ImportError: cannot import name 'BuildDependencyInstallError'`); delete it before each build, as in the commands above.
- `cryptography` uses a local recipe override (`p4a-recipes/cryptography/`, via `p4a.local_recipes`) that links its Rust extension against libpython; without it the module fails to load on Android (`cannot locate symbol "PyExc_TypeError"`).
- p4a's resolver only honours pins written with underscores (`paho_mqtt==2.1.0`, `charset_normalizer`); a hyphenated name gets the latest wheel added as well.
- The QR scanner is `com.journeyapps:zxing-android-embedded` via `android.gradle_dependencies` (Java only, no recipe). It doesn't ship AndroidX, so `androidx.core:core` is listed too. Don't `autoclass` its `IntentIntegrator`: that needs `androidx.fragment` and crashes at import. `android_qr.py` starts `CaptureActivity` with a plain Intent instead.
- pyjnius picks overloads by argument type and can choose wrongly (e.g. `Intent.setClassName(Context, String)`). Prefer overloads that take only strings or primitives. Exceptions raised inside `@run_on_ui_thread` code are only logged, so report them back to the Kivy thread.
- p4a reuses the built dist in `.buildozer/android/platform/build-arm64-v8a/dists/mqttchat`; after changing a recipe, delete that dist and the recipe's `build/other_builds/<recipe>` directory, or the APK won't change.

A local broker (e.g. `mosquitto` on `localhost:1883`, the UI defaults) is needed to exercise the chat flow.

`main.py` uses `mqtt.CallbackAPIVersion.VERSION1`, which needs paho-mqtt 2.x; keep the `buildozer.spec` pin on 2.x.

`connection_screen.py` and `buildozer.spec` use CRLF line endings; the other files use LF. Preserve them when editing (scripted rewrites in text mode silently convert CRLF to LF).

## Architecture

No `.kv` files — all UI is built in Python in `__init__`.

- `main.py` — `MQTTChatApp` owns all networking, encryption, and presence state, plus the `ScreenManager` with two screens (`'connection'`, `'chat'`). Screens never talk to MQTT directly; they call back into the app (`connect_to_mqtt`, `send_message`, `switch_to_connection`).
- `connection_screen.py` — form for username/broker/room/MQTT auth/encryption key; saved-room profiles; key generation and clipboard copy. Also QR exchange: Key QR / Room QR (in memory only, fingerprint, 60 s countdown, FLAG_SECURE) and Scan QR with an import confirmation. The QR buttons are only on this screen, not the chat screen.
- `chat_crypto.py` — all key handling, message encrypt/decrypt and the key fingerprint (no Kivy imports). `main.py` and `connection_screen.py` call into it.
- `qr_exchange.py` — builds and validates the two QR payloads (`mqttchat-key`, `mqttchat-room`; no Kivy imports). Scanned text is untrusted: it's validated here and escaped before display.
- `android_qr.py` — Android-only: FLAG_SECURE on the window while a QR is shown, and the ZXing scanner (result via `android.activity.bind(on_activity_result=...)`). Does nothing on desktop.
- `chat_screen.py` — renders messages into a single markup `Label` inside a `ScrollView`; the app pushes updates via `add_chat_message`, `add_system_message`, `update_users_list`.

### Threading

paho callbacks (`on_mqtt_connect`, `on_mqtt_message`, ...) run on paho's network thread (`loop_start()`), and heartbeat/cleanup use `threading.Timer`. Any UI change from these must go through `Clock.schedule_once(...)`. Disconnect runs in a daemon thread and finishes on the UI thread via `_finish_disconnect`.

### Wire protocol

`PROTOCOL.md` is the spec (topics, presence, AES-256-GCM payload, key rules, test vectors). Any change to `chat_crypto.py` or topic/payload handling must update `PROTOCOL.md`, because the separate desktop client (not in this repo) is ported from it. In brief:
- topics `chat/<room>/messages` and retained, unencrypted `chat/<room>/presence/<username>`;
- payload = `base64(0x01 || 12-byte nonce || AES-256-GCM ciphertext+tag)`, with the messages topic as AAD;
- a 44-char base64url key is used raw, anything else goes through scrypt with a room-derived salt.

Every connection uses a new random client ID (`mqttchat-<16 hex>`); never derive it from the name or config, or people sharing a room QR kick each other off. Disconnect must actually stop the old client (`switch_to_connection`): a leftover client with a reused ID causes a reconnect loop.

Own messages are rendered locally on send; incoming messages from the same username are dropped to avoid duplicates.

### Persistence

Saved rooms are JSON files in `rooms/` relative to the working directory (created at import time of `connection_screen.py`). They store the encryption key and MQTT password in plaintext.

## Current status (2026-11-04)

The work is split into four phases (1: AES-256-GCM crypto, 2: TLS, 3: QR export, 4: QR camera import). Phases 3/4 were replaced by Step 2 (in-person QR exchange). Do one step at a time and stop after each so the user can test. Use plan mode before editing, keep changes surgical, and commit after each step. The separate desktop client is deferred: change only this app, and keep `PROTOCOL.md` exact so it can be ported later.

**Step 1 (Phase 1, AES-256-GCM): done, tested on hardware.** Phone (Razr, arm64) ↔ desktop (this app under WSLg) messaging in room `chatty` on the test broker. Broker credentials and the test key live only in the gitignored `rooms/chatty.json` and the phone app's own `rooms/`, never in git.

**Step 2 (QR key and room exchange): done, tested on hardware.**
- Room QR scanned on the phone fills everything except the user's name.
- Key QR scanned on the phone updates the key, and the fingerprints match on both screens.
- FLAG_SECURE: screenshots of the app are black while a QR shows and normal after it closes.
- The QR auto-closes after 60 s.
- Two-way messaging works, including Disconnect → Connect on both sides with no reconnect loop.
- Rejections (wrong type or version, `tls: true`, non-app QR codes) are verified on desktop.

**Next:** Phase 2 (TLS) — wait for the user. When it lands, room QRs can carry `tls: true`, which `qr_exchange.parse` currently rejects.

**Known issues:**
- The APK bundles `chardet` 7.6.0 (Kivy → requests) as x86_64 `.so` files. Nothing imports it.
- `main.py` uses paho's deprecated callback API v1, which logs a warning.
- The user's separate desktop client still speaks the old Fernet format.
- ZXing's scan screen opens in landscape (the library's default).
- A room name from a key QR fills the form unchanged; `save_room` doesn't sanitize names, so a crafted name like `../x` could write outside `rooms/` if the user then taps Save Room. Key-only import itself refuses such names.
