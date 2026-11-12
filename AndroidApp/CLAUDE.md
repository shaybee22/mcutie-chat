# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Mcutie Chat (formerly MQTT Chat): a Kivy mobile (Android-targeted) client for end-to-end encrypted group chat over an MQTT broker. It is a port of a separate "desktop version" (not in this repo) and must stay wire-compatible with it — many comments say "same as desktop" for that reason. There are no tests, linter config, or README.

## Commands

```bash
# Run locally (desktop window)
pip install kivy paho-mqtt cryptography qrcode pillow
python main.py

# Run just the connection screen standalone (has its own __main__ test app)
python connection_screen.py

# Self-tests (no Kivy needed): crypto + fingerprint test vectors, QR payload rules, TLS context/CA rules
python3 chat_crypto.py
~/.venvs/mqttpeer/bin/python qr_exchange.py     # needs cryptography (CA validation)
~/.venvs/mqttpeer/bin/python tls_config.py      # needs cryptography + certifi
~/.venvs/mqttpeer/bin/python room_store.py      # saved-room store, with a fake Keystore cipher (needs cryptography)

# Build Android APK (config in buildozer.spec); output: bin/mcutiechat-1.1.0-arm64-v8a-debug.apk
source ~/.venvs/buildozer/bin/activate          # must be activated (VIRTUAL_ENV set), not just on PATH
export PATH="$HOME/.cargo/bin:$PATH"            # rustup/cargo: p4a builds cryptography from source
export PIP_NO_BINARY=charset-normalizer         # see the comment above `requirements` in buildozer.spec
rm -rf .buildozer/android/platform/build-arm64-v8a/build/venv   # p4a corrupts this venv on every rebuild
yes | buildozer android debug                   # `yes` accepts the SDK licences on first run

# Release APK (same prep as above): bin/mcutiechat-1.1.0-arm64-v8a-release.apk. The signing key is
# ~/.android-keys/mcutiechat-release.keystore (alias mcutiechat, PKCS12: one password), never in the repo.
# All four P4A_RELEASE_* vars are needed, or buildozer quietly builds an unsigned APK.
read -rsp 'Keystore password: ' P4A_RELEASE_KEYSTORE_PASSWD; echo
export P4A_RELEASE_KEYSTORE_PASSWD P4A_RELEASE_KEYALIAS_PASSWD="$P4A_RELEASE_KEYSTORE_PASSWD"
export P4A_RELEASE_KEYSTORE=~/.android-keys/mcutiechat-release.keystore P4A_RELEASE_KEYALIAS=mcutiechat
yes | buildozer android release
~/.buildozer/android/platform/android-sdk/build-tools/37.0.0/apksigner verify --print-certs bin/mcutiechat-1.1.0-arm64-v8a-release.apk

# Install and launch on the phone. If WSL's `adb devices` is empty (phone attached to Windows,
# not via usbipd), use Windows' adb.exe with a Windows path: adb.exe install -r "$(wslpath -w bin/...apk)"
# Debug and release builds have different signatures: switching needs `adb uninstall org.seumas.mcutiechat`
# first, which deletes the phone's saved rooms. Builds up to v1.0.0 kept rooms in files/app/rooms, which
# p4a deletes when any updated APK first starts, so `install -r` lost them too (see Persistence).
adb install -r bin/mcutiechat-1.1.0-arm64-v8a-debug.apk
adb shell monkey -p org.seumas.mcutiechat -c android.intent.category.LAUNCHER 1
adb logcat -s python:* SDL:* AndroidRuntime:*

# Run the app on the desktop (WSLg). Kivy 2.3.1 has no Python 3.14 wheels, so use the 3.12 venv
~/.venvs/mqttdesk/bin/python main.py

# Headless test peer (venv: ~/.venvs/mqttpeer with paho-mqtt 2.1.0 + cryptography + certifi)
CHAT_KEY=... MQTT_PASSWORD=... ~/.venvs/mqttpeer/bin/python tools/test_peer.py \
    --host BROKER --room ROOM --mqtt-user USER --send "hello" --duration 60
#   add --tls (public CAs) or --tls --ca ca.pem (pinned) for TLS brokers
```

TLS testing without a TLS broker: run a TLS-terminating proxy in WSL that forwards to the broker's plain port, using a throwaway CA made with the `openssl` recipe in `PROTOCOL.md`. Then `adb.exe reverse tcp:8883 tcp:8883` lets the phone reach it as `localhost:8883`. This was done in session scratch space and isn't kept in the repo.

Build quirks (all with p4a master + Python 3.14 host, Oct 2026):
- `kivy` is pinned to 2.3.1 because p4a's kivy recipe patches that release; `kivy==master` fails at patching.
- arm64-v8a only: `cryptography` fails to build for armeabi-v7a (p4a passes host x86_64 Python headers → `LONG_BIT` error).
- p4a's build venv (`.buildozer/.../build/venv`) ends up with a half-upgraded pip on every rebuild (`ImportError: cannot import name 'BuildDependencyInstallError'`); delete it before each build, as in the commands above.
- `cryptography` uses a local recipe override (`p4a-recipes/cryptography/`, via `p4a.local_recipes`) that links its Rust extension against libpython; without it the module fails to load on Android (`cannot locate symbol "PyExc_TypeError"`).
- p4a's resolver only honours pins written with underscores (`paho_mqtt==2.1.0`, `charset_normalizer`); a hyphenated name gets the latest wheel added as well.
- The QR scanner is `com.journeyapps:zxing-android-embedded` via `android.gradle_dependencies` (Java only, no recipe). It doesn't ship AndroidX, so `androidx.core:core` is listed too. Don't `autoclass` its `IntentIntegrator`: that needs `androidx.fragment` and crashes at import. `android_qr.py` starts `CaptureActivity` with a plain Intent instead.
- pyjnius picks overloads by argument type and can choose wrongly (e.g. `Intent.setClassName(Context, String)`). Prefer overloads that take only strings or primitives. It doesn't check assignability: an object argument scores the same for every overload of that arity unless its wrapped class matches the declared parameter type exactly, so `cast()` objects to the declared type (`cast("java.security.spec.AlgorithmParameterSpec", GCMParameterSpec(...))`). A wrong pick aborts the app. For `String...` varargs pass the strings themselves (`setBlockModes("GCM")`): pyjnius packs them into the array, and a Python list ends up as a `String[]` inside it, which aborts the app (`ArrayStoreException` in JNI, not catchable). Exceptions raised inside `@run_on_ui_thread` code are only logged, so report them back to the Kivy thread.
- `BiometricPrompt.AuthenticationCallback` is an abstract class, and pyjnius can only implement interfaces. `src/org/seumas/mcutiechat/AuthCallback.java` (via `android.add_src = src`) forwards it to the `AuthListener` interface, which `android_auth.py` implements with a `PythonJavaClass` (`__javacontext__ = "app"`).
- p4a reuses the built dist in `.buildozer/android/platform/build-arm64-v8a/dists/mcutiechat`; after changing a recipe, delete that dist and the recipe's `build/other_builds/<recipe>` directory, or the APK won't change.

A local broker (e.g. `mosquitto` on `localhost:1883`, the UI defaults) is needed to exercise the chat flow.

`main.py` uses `mqtt.CallbackAPIVersion.VERSION1`, which needs paho-mqtt 2.x; keep the `buildozer.spec` pin on 2.x.

`connection_screen.py` and `buildozer.spec` use CRLF line endings; the other files use LF. Preserve them when editing (scripted rewrites in text mode silently convert CRLF to LF).

## Architecture

No `.kv` files — all UI is built in Python in `__init__`.

- `main.py` — `MQTTChatApp` owns all networking, encryption, and presence state, plus the `ScreenManager` with two screens (`'connection'`, `'chat'`). Screens never talk to MQTT directly; they call back into the app (`connect_to_mqtt`, `send_message`, `switch_to_connection`).
- `connection_screen.py` — form for username/broker/room/MQTT auth/encryption key; saved-room profiles; key generation and clipboard copy. Also QR exchange: Key QR / Room QR (in memory only, fingerprint, 60 s countdown, FLAG_SECURE) and Scan QR with an import confirmation. The QR buttons are only on this screen, not the chat screen. Also the TLS checkbox (1883 ↔ 8883) and the CA PEM box (desktop: also load from a file). Rooms save `tls` and `ca`. QR codes are drawn at whole pixels per module on whole-pixel coordinates: fractional scaling made them unscannable.
- `chat_crypto.py` — all key handling, message encrypt/decrypt and the key fingerprint (no Kivy imports). `main.py` and `connection_screen.py` call into it.
- `qr_exchange.py` — builds and validates the two QR payloads (`mqttchat-key`, `mqttchat-room`; no Kivy imports). Scanned text is untrusted: it's validated here and escaped before display.
- `tls_config.py` — TLS client context (no Kivy imports): pinned to the room's CA if it has one, otherwise the certifi list. Always verified, hostname checked, TLS 1.2+, strict X.509. Also validates and describes CA PEMs.
- `android_qr.py` — Android-only: FLAG_SECURE on the window while a QR is shown, and the ZXing scanner (result via `android.activity.bind(on_activity_result=...)`). Does nothing on desktop.
- `room_store.py` — saved rooms (no Kivy imports): location, Keystore encryption, migration. See Persistence.
- `android_auth.py` — Android-only: the `BiometricPrompt` with a `CryptoObject` that authorizes one use of the saved-rooms Keystore key (strong biometric or screen-lock PIN). Reports "error" on desktop, where nothing locks.
- `chat_screen.py` — renders messages into a single markup `Label` inside a `ScrollView`; the app pushes updates via `add_chat_message`, `add_system_message`, `update_users_list`.

### Threading

paho callbacks (`on_mqtt_connect`, `on_mqtt_message`, ...) run on paho's network thread (`loop_start()`), and heartbeat/cleanup use `threading.Timer`. Any UI change from these must go through `Clock.schedule_once(...)`. Disconnect runs in a daemon thread and finishes on the UI thread via `_finish_disconnect`.

### Wire protocol

`PROTOCOL.md` is the spec (topics, presence, AES-256-GCM payload, key rules, test vectors). Any change to `chat_crypto.py` or topic/payload handling must update `PROTOCOL.md`. The desktop client (`../mqchat.py`) imports `chat_crypto`, `qr_exchange` and `tls_config` from this folder, so changes here affect both clients; test both. In brief:
- topics `chat/<room>/messages` and retained, unencrypted `chat/<room>/presence/<username>`;
- payload = `base64(0x01 || 12-byte nonce || AES-256-GCM ciphertext+tag)`, with the messages topic as AAD;
- a 44-char base64url key is used raw, anything else goes through scrypt with a room-derived salt.

Every connection uses a new random client ID (`mqttchat-<16 hex>`); never derive it from the name or config, or people sharing a room QR kick each other off. Disconnect must actually stop the old client (`switch_to_connection`): a leftover client with a reused ID causes a reconnect loop.

Own messages are rendered locally on send; incoming messages from the same username are dropped to avoid duplicates.

### Persistence

`room_store.py` holds all saved-room file access; `connection_screen.py` calls it through `_with_store`, which prompts and retries once when the key is locked and never lets a storage error escape.

- **Where:** `<App.user_data_dir>/rooms`. On Android that is `files/rooms`. Never under `files/app`: p4a deletes `files/app` the first time each new build starts (`unpackAsset(..., true)` in its `PythonActivity.java`, triggered by `private_version`, which includes the build time). That is how v1.0.0's `./rooms` was lost on every update, and why v1.0.0 rooms can't be migrated (they're gone before Python runs). Desktop: `~/.config/mqttchat/rooms`.
- **Android format (needs API 30, `android.minapi = 30`; `android.ndk_api` stays 24 so the native builds don't change):** `<16 random hex>.room` = `0x02 || 12-byte nonce || AES-256-GCM ciphertext+tag` of `{"name": ..., "room": {...}}`, AAD `mcutiechat-room:<file id>`, encrypted in Python with the data key. Room names are inside the ciphertext, so nothing is listed while locked.
- **Keys:** a wrapping key in the Android Keystore, alias `mcutiechat-rooms-kek`, non-exportable, `setUserAuthenticationParameters(0, BIOMETRIC_STRONG | DEVICE_CREDENTIAL)`: every use needs its own prompt bound to that `Cipher` (CryptoObject); unlocking the phone doesn't count. It wraps a random 32-byte data key in `files/rooms/datakey.bin` (`0x01 || 12-byte IV || AES-GCM(data key)+tag`, AAD `mcutiechat-datakey`). One prompt per app session unwraps the data key into memory (`room_store.begin_unlock()` → `android_auth.authenticate()` → `finish_unlock()`); `main.py`'s `on_pause`/`on_stop` call `room_store.lock()`, which zeroes and drops it. Creating the wrapping key needs a secure screen lock; without one, saving shows "Set a screen lock to save rooms". Removing the screen lock invalidates it: the app offers to clear the saved rooms (files, `datakey.bin`, both aliases). Fingerprint changes don't.
- **UI:** the spinner says "Locked - tap to unlock" until the first tap of each session unlocks (no prompt at app start). Cancel leaves it locked; manual entry and QR scan still work. Going to the background (including opening the QR scanner) locks again.
- **Migration (after each unlock, until nothing is left):** version-1 `.room` files (the earlier format: encrypted directly by the 5-minute Keystore key `mcutiechat-rooms`) are decrypted with that key (the prompt that just succeeded counts as recent auth for it), re-encrypted as version 2, checked, then deleted; the old alias is deleted when none remain. Plaintext `*.json` in the rooms folder or the old `./rooms` is encrypted, checked, then deleted. Names that already exist are skipped and the old file left alone.
- **Desktop/dev:** no Keystore, so plaintext `<name>.json` as before (`valid_name` refuses slashes, `.` and `..`). Android never falls back to plaintext: without a Keystore, saved rooms are disabled.
- Never print room contents, keys or Java exception messages; `room_store` errors are fixed strings.

## Current status (2026-11-05)

**Working style the user expects:**
- plan mode before editing;
- surgical changes;
- one step at a time, stopping so they can test;
- commit per step, on a branch, then PR + merge with **merge commits** (never squash: the Android history was subtree-merged into `AndroidApp/`);
- no tags or releases without the user's go-ahead.

**Where we are:** **v1.0.0 is released** (tag on `672d2ad`, https://github.com/shaybee22/mcutie-chat/releases/tag/v1.0.0) with the signed release APK, `McutieChat-1.0.0-windows-x64.exe` and `SHA256SUMS.txt`. Everything is on `main` of `shaybee22/mcutie-chat`:
- #1: Android app (protocol v1), rename, `install.sh`;
- #2: app icon;
- #3: the desktop client on protocol v1;
- #4: saved rooms no longer packed into the APK;
- #6: release prep: root `.gitignore` (desktop saved rooms, PyInstaller output, keystores), version `1.0.0`, release artifact `apk`;
- #7: README points to the v1.0.0 release;
- #9: root `README.md` rewritten for v1.0.0 (what it is, encryption, QR exchange, downloads, Linux from source, own broker). It links to `AndroidApp/README.md`, `Linux/README.md`, `BROKER-SETUP.md` and `PROTOCOL.md` instead of repeating them; keep it that way, and update its download links on each release.
- #10: chat markup escaped, Android backup off, broker limits in `install.sh`;
- #11: saved rooms in `files/rooms` (survive updates), encrypted with a data key wrapped by a per-use Keystore key (fingerprint/PIN once per app session); `minapi` 30.
- Next: v1.1.0 (version bumped, READMEs point to v1.1.0; the Windows row keeps the unchanged v1.0.0 exe). Not tagged yet: the release needs `mcutiechat-1.1.0-arm64-v8a-release.apk` and its `SHA256SUMS.txt`.

**Tested on hardware:**
- v1.1.0 saved rooms (debug build, Razr Ultra 2025, Android 16): prompt right after a phone unlock, cancel, fingerprint and PIN, re-lock on Home, v1→v2 migration, no plaintext left in app storage, `install -r` update keeps rooms. Release build installed and starts.
- The signed release APK on the phone (after uninstalling the debug build): connect, messages, Room QR scan, Disconnect → Connect.
- The Windows `.exe` (`build_mqchat.bat`) against the user's real cloud broker: icons, connect, messages with the phone, Room QR scanned by the phone, Disconnect → Connect.
- Android (Razr, arm64) ↔ desktop client (`../mqchat.py`) ↔ the Kivy app on desktop.
- Plain and TLS: a pinned self-signed CA through a local proxy, plus public CAs via the test peer.
- Room/Key QR in both directions (desktop shows → phone scans; desktop imports pasted QR text).
- FLAG_SECURE, and Disconnect → Connect with no reconnect loop.
- `install.sh` on a Proxmox Ubuntu 26.04 VM: self-signed and no TLS, re-runs, `--add-user`, CA key removal, SSH restriction, port change.

**Not tested yet:**
- `install.sh` with Let's Encrypt (`BROKER-SETUP.md` says untested);
- TLS with a publicly trusted certificate on the phone itself.

**Next:** nothing planned; wait for the user.

**For future releases:**
- Bump `version` in `buildozer.spec`; p4a derives the versionCode from it, so it must increase.
- Sign every release APK with the same keystore (`~/.android-keys/mcutiechat-release.keystore`, alias `mcutiechat`). The user keeps it and its password backed up off this machine; a different key means users must uninstall and lose their saved rooms.
- Windows: `build_mqchat.bat` must run from a Windows folder; cmd can't `cd` into `\\wsl.localhost\...`. Name the asset `McutieChat-<version>-windows-x64.exe`.
- Attach `SHA256SUMS.txt`, and update the README release link before tagging, so the tagged README is right.

**Known issues:**
- The APK bundles `chardet` 7.6.0 (Kivy → requests) as x86_64 `.so` files. Nothing imports it.
- `main.py` uses paho's deprecated callback API v1, which logs a warning.
- The desktop client's saved-rooms file is obfuscated with a key built into the code, not protected (README notes it; an OS keyring is on the roadmap).
- ZXing's scan screen opens in landscape (the library's default).
- Upgrading from v1.0.0 loses the phone's saved rooms once (p4a's `files/app` wipe, see Persistence); later updates keep them. Say so in the next release notes.
- "Clear Fields" in the desktop client resets the key to the placeholder passphrase `supersecretkey123`.
