#!/usr/bin/env python3
"""
Mcutie Chat by James Powell
A simple encrypted group chat using MQTT as the relay server
FINAL VERSION - Anti-spam join detection

Speaks Mcutie Chat protocol v1 (AndroidApp/PROTOCOL.md): AES-256-GCM messages, QR room/key
exchange, optional TLS. The protocol code is shared with the Android app (AndroidApp/).
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import tkinter.font as tkfont
import paho.mqtt.client as mqtt
import json
import base64
import hashlib
import time
import threading
import os
import sys
import secrets
from datetime import datetime

# Protocol code shared with the Android app: one copy, so the clients can't drift apart.
# (A PyInstaller build bundles these modules via --paths AndroidApp.)
_APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AndroidApp")
if os.path.isdir(_APP_DIR):
    sys.path.insert(0, _APP_DIR)
import chat_crypto  # noqa: E402
import qr_exchange  # noqa: E402
import tls_config  # noqa: E402

QR_TIMEOUT = 60       # seconds a key/room QR stays on screen
QR_MAX_VERSION = 25   # larger QR codes may not scan reliably off a screen

# ---- Chat colors: each username hashes to a fixed palette entry (stable across sessions).
# All colors have at least 4.5:1 contrast on CHAT_BG (checked by --self-test).
CHAT_BG = "#FFFFFF"
MY_COLOR = "#1565C0"        # our own messages: always this blue, which isn't in USER_COLORS
SYSTEM_COLOR = "#6B6B6B"    # system messages: grey italic
USER_COLORS = ("#C62828", "#AD1457", "#6A1B9A", "#00838F", "#2E7D32",
               "#827717", "#BF360C", "#5D4037", "#455A64", "#9A5B00")


def user_color_index(name):
    """Index into USER_COLORS for a username (sha256, so the same in every session)."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % len(USER_COLORS)


# ---- Saved rooms (mqtt_chat_rooms.json) and Export All files.
# Saved rooms: AES-256-GCM with a random 256-bit data key kept in the OS keyring (Windows
# Credential Manager / Secret Service). With no usable keyring: a key derived (scrypt) from a
# passphrase asked once per session. Exports: always a passphrase chosen at export time.
# Both files are JSON: header fields + "nonce" + "ct" (base64); the header is the GCM AAD.
ROOMS_FORMAT = "mcutie-rooms"
ROOMS_VERSION = 2               # version 1 was the fixed-key Fernet file (obfuscation only)
EXPORT_FORMAT = "mcutie-rooms-export"
EXPORT_VERSION = 1
KEYRING_SERVICE = "Mcutie Chat"
KEYRING_ENTRY = "saved-rooms-data-key"
PASS_SCRYPT_N = 2 ** 17         # stronger than the chat's 2**15: these files can be attacked offline
PASS_SCRYPT_R = 8
PASS_SCRYPT_P = 1
SALT_SIZE = 16
MIN_PASSPHRASE = 8


class RoomsFileError(Exception):
    """A saved-rooms or export file problem; the message is shown to the user."""


def _legacy_fernet():
    from cryptography.fernet import Fernet
    # The old fixed key built into the code: only read, to migrate old files
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"mqtt_chat_config_key_v1").digest()))


def _check_rooms(rooms):
    if not isinstance(rooms, dict) or not all(
            isinstance(k, str) and isinstance(v, dict) for k, v in rooms.items()):
        raise RoomsFileError("The file doesn't contain a list of rooms.")
    return rooms


def _aad(header):
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _passphrase_header(fmt, version, salt=None):
    return {"format": fmt, "version": version, "kdf": "scrypt",
            "salt": base64.b64encode(salt or os.urandom(SALT_SIZE)).decode(),
            "n": PASS_SCRYPT_N, "r": PASS_SCRYPT_R, "p": PASS_SCRYPT_P}


def _passphrase_key(passphrase, header):
    try:
        salt = base64.b64decode(header["salt"], validate=True)
        n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
    except (KeyError, TypeError, ValueError):
        raise RoomsFileError("The file's passphrase settings are damaged.")
    if not (2 ** 14 <= n <= 2 ** 20 and 1 <= r <= 16 and 1 <= p <= 4 and len(salt) >= 16):
        raise RoomsFileError("The file's passphrase settings are not supported.")
    kdf = chat_crypto.Scrypt(salt=salt, length=chat_crypto.KEY_SIZE, n=n, r=r, p=p)
    return kdf.derive(passphrase.encode("utf-8"))


def _seal_rooms(key, header, rooms):
    nonce = os.urandom(chat_crypto.NONCE_SIZE)
    ct = chat_crypto.AESGCM(key).encrypt(nonce, json.dumps(rooms).encode("utf-8"), _aad(header))
    return json.dumps(dict(header, nonce=base64.b64encode(nonce).decode(),
                           ct=base64.b64encode(ct).decode()), indent=1).encode("utf-8")


def _split_envelope(env):
    """Return (header, nonce, ct) of a parsed file, or raise RoomsFileError."""
    header = {k: v for k, v in env.items() if k not in ("nonce", "ct")}
    try:
        nonce = base64.b64decode(env["nonce"], validate=True)
        ct = base64.b64decode(env["ct"], validate=True)
    except (KeyError, TypeError, ValueError):
        raise RoomsFileError("The file is damaged.")
    if len(nonce) != chat_crypto.NONCE_SIZE:
        raise RoomsFileError("The file is damaged.")
    return header, nonce, ct


def _open_rooms(key, env):
    """Decrypt a parsed file; raises cryptography's InvalidTag for a wrong key or tampering."""
    header, nonce, ct = _split_envelope(env)
    plain = chat_crypto.AESGCM(key).decrypt(nonce, ct, _aad(header))
    return _check_rooms(json.loads(plain.decode("utf-8")))


def _write_private(path, data):
    """Write atomically, readable only by this user on Linux/macOS (no plaintext ever lands here)."""
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RoomsFileError(f"Could not write {path}: {e}")


def _wrong_passphrase(ask, prompt, attempt):
    """Ask for a passphrase, telling the user when the previous one was wrong."""
    return ask(("Wrong passphrase, try again.\n\n" if attempt else "") + prompt, False)


def export_rooms_data(rooms, passphrase):
    """Encrypted Export All file contents (bytes)."""
    header = _passphrase_header(EXPORT_FORMAT, EXPORT_VERSION)
    return _seal_rooms(_passphrase_key(passphrase, header), header, _check_rooms(rooms))


def import_rooms_data(data, ask):
    """Parse an Export All file. Returns (rooms, was_plaintext), or (None, False) if cancelled.

    ask(prompt, confirm) -> passphrase or None. Plaintext exports (older versions) are
    returned with was_plaintext=True so the caller can warn before importing them.
    """
    try:
        env = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise RoomsFileError("This isn't a Mcutie Chat rooms export.")
    if not (isinstance(env, dict) and env.get("format") == EXPORT_FORMAT):
        if isinstance(env, dict) and env.get("format") == ROOMS_FORMAT:
            raise RoomsFileError("This is a saved-rooms file, not an export. Use Export All to make one.")
        return _check_rooms(env), True
    if env.get("version") != EXPORT_VERSION or env.get("kdf") != "scrypt":
        raise RoomsFileError("This export was made by a newer version of Mcutie Chat.")
    from cryptography.exceptions import InvalidTag
    attempt = 0
    while True:
        passphrase = _wrong_passphrase(ask, "Enter the passphrase this export was protected with:", attempt)
        if passphrase is None:
            return None, False
        try:
            return _open_rooms(_passphrase_key(passphrase, env), env), False
        except InvalidTag:
            attempt += 1


def _system_keyring():
    """The keyring module if a real backend is usable here, else None."""
    try:
        import keyring
        backend = keyring.get_keyring()
    except Exception:
        return None
    if type(backend).__module__ in ("keyring.backends.fail", "keyring.backends.null"):
        return None
    return keyring


class RoomVault:
    """Reads and writes the encrypted saved-rooms file.

    It never writes rooms in plaintext, and never overwrites a file it couldn't open ("locked").
    ask(prompt, confirm) -> passphrase or None (cancel); confirm=True means choose a new one.
    """

    def __init__(self, path, keyring_module="system"):
        self.path = path
        self.keyring = _system_keyring() if keyring_module == "system" else keyring_module
        self.mode = "keyring" if self.keyring else "passphrase"
        self.key = None
        self.header = None        # header of the file being written (holds the passphrase salt)
        self.locked = None        # reason the existing file couldn't be opened, or None
        self.locked_env = None    # its parsed contents, if a passphrase could still unlock it
        self.legacy_pending = False  # rooms came from an old-format file not yet rewritten

    # -- keyring
    def _keyring_key(self, create):
        """The data key from the keyring (made on first use if create). None if unavailable/absent."""
        if not self.keyring:
            return None
        try:
            stored = self.keyring.get_password(KEYRING_SERVICE, KEYRING_ENTRY)
            if stored is None and create:
                self.keyring.set_password(KEYRING_SERVICE, KEYRING_ENTRY, chat_crypto.generate_key())
                stored = self.keyring.get_password(KEYRING_SERVICE, KEYRING_ENTRY)  # verify it stuck
        except Exception as e:
            print(f"Keyring unavailable: {e}")
            return None
        if stored is None:
            return None
        key = chat_crypto.parse_raw_key(stored)
        if key is None:
            raise RoomsFileError("The saved-rooms key in the system keyring is damaged.")
        return key

    def _use_keyring(self):
        """Switch to a keyring data key; False (passphrase mode) if there's no usable keyring."""
        key = self._keyring_key(create=True)
        if key is None:
            self.mode = "passphrase"
            return False
        self.mode, self.key = "keyring", key
        self.header = {"format": ROOMS_FORMAT, "version": ROOMS_VERSION, "kdf": "keyring"}
        return True

    # -- reading
    def _read(self):
        """('missing'|'legacy'|'v2', rooms or parsed file)."""
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            return "missing", None
        except OSError as e:
            raise RoomsFileError(f"Could not read {self.path}: {e}")
        try:
            env = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            env = None
        if isinstance(env, dict) and env.get("format") == ROOMS_FORMAT:
            if env.get("version") != ROOMS_VERSION or env.get("kdf") not in ("keyring", "scrypt"):
                raise RoomsFileError("The saved-rooms file was made by a newer version of Mcutie Chat.")
            return "v2", env
        try:
            plain = _legacy_fernet().decrypt(data.strip())
        except Exception:
            raise RoomsFileError("The saved-rooms file isn't in a format this version recognises.")
        return "legacy", _check_rooms(json.loads(plain.decode("utf-8")))

    def _unlock_passphrase(self, env, ask):
        """Ask until the passphrase opens env. Returns rooms, or None if cancelled."""
        from cryptography.exceptions import InvalidTag
        attempt = 0
        while True:
            passphrase = _wrong_passphrase(
                ask, "Saved rooms are protected with a passphrase (no system keyring).\n"
                     "Enter it to unlock them for this session:", attempt)
            if passphrase is None:
                return None
            key = _passphrase_key(passphrase, env)
            try:
                rooms = _open_rooms(key, env)
            except InvalidTag:
                attempt += 1
                continue
            self.mode, self.key = "passphrase", key
            self.header = {k: env[k] for k in _passphrase_header(ROOMS_FORMAT, ROOMS_VERSION)}
            return rooms

    def load(self, ask):
        """Rooms from the file ({} if none). Migrates an old-format file, and a passphrase file
        once a keyring is available. Raises RoomsFileError, and the vault is then locked."""
        self.locked = self.locked_env = None
        try:
            return self._load(ask)
        except Exception as e:
            if not self.locked:
                self.locked = str(e) if isinstance(e, RoomsFileError) else f"Unexpected error: {e}"
            raise RoomsFileError(self.locked) from e

    def _rewrite(self, rooms, ask):
        """Rewrite in the current format; on failure the old file stays and rooms stay in memory."""
        try:
            self.save(rooms, ask)
        except RoomsFileError as e:
            print(f"Saved rooms not rewritten yet: {e}")

    def _load(self, ask):
        from cryptography.exceptions import InvalidTag
        kind, content = self._read()
        if kind == "missing":
            return {}
        if kind == "legacy":
            self.legacy_pending = True
            self._rewrite(content, ask)   # replaces the old-format file with the new format
            return content
        if content["kdf"] == "keyring":
            key = self._keyring_key(create=False)
            if key is None:
                self.locked = ("They're encrypted with a key in the system keyring, which isn't "
                               "available (a different user, computer or keyring?).")
                raise RoomsFileError(self.locked)
            try:
                rooms = _open_rooms(key, content)
            except InvalidTag:
                self.locked = "The keyring's key doesn't open them (the file was changed or the key replaced)."
                raise RoomsFileError(self.locked)
            self._use_keyring()
            return rooms
        rooms = self._unlock_passphrase(content, ask)
        if rooms is None:
            self.locked, self.locked_env = "No passphrase entered.", content
            return {}
        if self.keyring and self._use_keyring():
            self._rewrite(rooms, ask)  # a keyring is available now: move off the passphrase
        return rooms

    # -- writing
    def save(self, rooms, ask):
        """Encrypt and write rooms; returns the rooms written (a still-locked file's rooms are
        merged in once unlocked). Raises RoomsFileError, writing nothing, if there's no key."""
        _check_rooms(rooms)
        if self.locked:
            if self.locked_env is None:
                raise RoomsFileError(f"The saved-rooms file couldn't be opened, so it was left untouched. "
                                     f"{self.locked}")
            existing = self._unlock_passphrase(self.locked_env, ask)
            if existing is None:
                raise RoomsFileError("The saved rooms are still locked (no passphrase entered), "
                                     "so the file was left untouched.")
            self.locked = self.locked_env = None
            rooms = {**existing, **rooms}
            if self.keyring:
                self._use_keyring()
        if self.key is None and not (self.mode == "keyring" and self._use_keyring()):
            passphrase = ask("No system keyring is available, so saved rooms are protected with a "
                             "passphrase.\nChoose one (you'll enter it each time you start Mcutie Chat):",
                             True)
            if passphrase is None:
                raise RoomsFileError("No passphrase chosen, so nothing was written.")
            self.header = _passphrase_header(ROOMS_FORMAT, ROOMS_VERSION)
            self.mode, self.key = "passphrase", _passphrase_key(passphrase, self.header)
        _write_private(self.path, _seal_rooms(self.key, self.header, rooms))
        self.legacy_pending = False
        return rooms

    def describe(self):
        """One line for the Saved Rooms tab."""
        if self.locked:
            return f"⛔ Saved rooms are locked and the file is left untouched. {self.locked}"
        if self.legacy_pending:
            return ("⚠️ Saved rooms are still in the old, obfuscated-only format: "
                    "save a room to encrypt them properly.")
        if self.mode == "keyring":
            where = "Windows Credential Manager" if os.name == "nt" else "the system keyring"
            return f"🔒 Saved rooms are encrypted (AES-256-GCM) with a key kept in {where}."
        return ("⚠️ No system keyring found: saved rooms are encrypted with a passphrase "
                "you enter each session.")

class SecureMQTTChat:
    def _set_window_icon(self):
        """Window/taskbar icon; next to this script, or inside a PyInstaller bundle"""
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        try:
            ico = os.path.join(base, "mcutie-icon.ico")
            if os.name == "nt" and os.path.exists(ico):
                self.root.iconbitmap(default=ico)  # multi-resolution, used for the taskbar too
            else:
                self._icon_image = tk.PhotoImage(file=os.path.join(base, "mcutie-icon.png"))
                self.root.iconphoto(True, self._icon_image)
        except Exception as e:
            print(f"Window icon not set: {e}")  # cosmetic only: never stop the app over it

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Mcutie Chat by James Powell")
        self._set_window_icon()
        self.root.geometry("900x800")
        
        # MQTT and crypto variables
        self.mqtt_client = None
        self.key = None  # 32-byte AES-256-GCM room key
        self.connected = False
        self.username = ""
        self.channel = ""
        self.encryption_key = ""
        
        # Topics
        self.messages_topic = ""
        self.presence_topic = ""
        self.userlist_topic = ""
        
        # User tracking
        self.online_users = set()
        self.heartbeat_timer = None
        self.recent_joins = {}  # Track recent joins to prevent spam
        
        # Room management
        self.config_file = "mqtt_chat_rooms.json"
        self.room_vault = RoomVault(self.config_file)
        self.saved_rooms = {}
        
        self.setup_gui()
        self.load_saved_rooms()
        
    def clear_my_presence(self):
        """Clear our own presence message to prevent duplicates"""
        if self.mqtt_client and self.username:
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", "", retain=True)

    def force_clean_users(self):
        """Force clean the users list by removing duplicates"""
        # Convert to list, remove duplicates, convert back to set
        unique_users = list(set(self.online_users))
        self.online_users = set(unique_users)
        self.update_users_list()

    def nuclear_clean_users(self):
        """Nuclear option - completely rebuild user list"""
        print("Nuclear clean - rebuilding user list")
        self.online_users.clear()
        self.online_users.add(self.username)  # Add ourselves back
        self.update_users_list()
        
    def clear_connection_fields(self):
        """Clear all connection fields"""
        self.server_entry.delete(0, tk.END)
        self.server_entry.insert(0, "localhost")
        
        self.port_entry.delete(0, tk.END)
        self.port_entry.insert(0, "1883")
        
        self.channel_entry.delete(0, tk.END)
        self.channel_entry.insert(0, "general")
        
        self.username_entry.delete(0, tk.END)
        
        self.mqtt_username_entry.delete(0, tk.END)
        self.mqtt_password_entry.delete(0, tk.END)
        
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, "supersecretkey123")
        
        self.tls_var.set(False)
        self.set_ca("")
        
        # Clear dropdown selection
        self.rooms_var.set("")
        
        self.update_key_display()
        messagebox.showinfo("Cleared", "All fields cleared to defaults!")
        
    def setup_gui(self):
        """Create the GUI layout"""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Connection tab
        self.connection_frame = ttk.Frame(notebook)
        notebook.add(self.connection_frame, text="Connection")
        self.setup_connection_tab()
        
        # Chat tab
        self.chat_frame = ttk.Frame(notebook)
        notebook.add(self.chat_frame, text="Chat")
        self.setup_chat_tab()
        
        # Room Management tab
        self.rooms_frame = ttk.Frame(notebook)
        notebook.add(self.rooms_frame, text="Saved Rooms")
        self.setup_rooms_tab()
        
    def setup_connection_tab(self):
        """Setup the connection configuration tab"""
        # Title
        title_label = tk.Label(self.connection_frame, text="Mcutie Chat Configuration", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=12)
        
        # Quick Load Frame
        quick_frame = tk.LabelFrame(self.connection_frame, text="Quick Connect", 
                                   font=("Arial", 10, "bold"))
        quick_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # Saved rooms dropdown
        rooms_frame = tk.Frame(quick_frame)
        rooms_frame.pack(pady=10)
        
        tk.Label(rooms_frame, text="Saved Rooms:").pack(side=tk.LEFT, padx=5)
        self.rooms_var = tk.StringVar()
        self.rooms_dropdown = ttk.Combobox(rooms_frame, textvariable=self.rooms_var, 
                                          state="readonly", width=25)
        self.rooms_dropdown.pack(side=tk.LEFT, padx=5)
        self.rooms_dropdown.bind('<<ComboboxSelected>>', self.load_room_config)
        
        load_btn = tk.Button(rooms_frame, text="Load Room", command=self.load_room_config,
                           bg="#4CAF50", fg="white")
        load_btn.pack(side=tk.LEFT, padx=5)
        
        import_qr_btn = tk.Button(rooms_frame, text="Import QR text...", command=self.import_qr_text)
        import_qr_btn.pack(side=tk.LEFT, padx=5)
        
        # Configuration frame
        config_frame = tk.LabelFrame(self.connection_frame, text="Manual Configuration", 
                                    font=("Arial", 10, "bold"))
        config_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # Create inner frame for grid layout
        inner_config = tk.Frame(config_frame)
        inner_config.pack(pady=10)
        
        # MQTT Server
        tk.Label(inner_config, text="MQTT Server:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.server_entry = tk.Entry(inner_config, width=30)
        self.server_entry.grid(row=0, column=1, padx=5, pady=5)
        self.server_entry.insert(0, "localhost")
        
        # Port
        tk.Label(inner_config, text="Port:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.port_entry = tk.Entry(inner_config, width=30)
        self.port_entry.grid(row=1, column=1, padx=5, pady=5)
        self.port_entry.insert(0, "1883")
        
        # Channel/Room
        tk.Label(inner_config, text="Channel:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.channel_entry = tk.Entry(inner_config, width=30)
        self.channel_entry.grid(row=2, column=1, padx=5, pady=5)
        self.channel_entry.insert(0, "general")
        
        # MQTT Authentication frame
        auth_frame = tk.LabelFrame(inner_config, text="MQTT Authentication (Optional)", 
                                  font=("Arial", 9, "italic"))
        auth_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=10)
        
        # MQTT Username
        tk.Label(auth_frame, text="MQTT Username:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        self.mqtt_username_entry = tk.Entry(auth_frame, width=25)
        self.mqtt_username_entry.grid(row=0, column=1, padx=5, pady=3)
        
        # MQTT Password
        tk.Label(auth_frame, text="MQTT Password:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.mqtt_password_entry = tk.Entry(auth_frame, width=25, show="*")
        self.mqtt_password_entry.grid(row=1, column=1, padx=5, pady=3)
        
        # Show MQTT password checkbox
        self.show_mqtt_password_var = tk.BooleanVar()
        show_mqtt_pass_btn = tk.Checkbutton(auth_frame, text="Show Password", 
                                           variable=self.show_mqtt_password_var,
                                           command=self.toggle_mqtt_password_visibility)
        show_mqtt_pass_btn.grid(row=1, column=2, sticky="w", padx=5, pady=3)
        
        # Help text
        help_label = tk.Label(auth_frame, text="Leave blank for anonymous connection", 
                             font=("Arial", 8), fg="gray")
        help_label.grid(row=2, column=0, columnspan=3, pady=3)
        
        # Chat Username
        tk.Label(inner_config, text="Chat Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        self.username_entry = tk.Entry(inner_config, width=30)
        self.username_entry.grid(row=4, column=1, padx=5, pady=5)
        
        # Encryption Key
        tk.Label(inner_config, text="Encryption Key:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        self.key_entry = tk.Entry(inner_config, width=30, show="*")
        self.key_entry.grid(row=5, column=1, padx=5, pady=5)
        self.key_entry.insert(0, "supersecretkey123")
        
        # Key buttons frame
        key_buttons_frame = tk.Frame(inner_config)
        key_buttons_frame.grid(row=5, column=2, padx=5, pady=5)
        
        # Generate key button
        generate_btn = tk.Button(key_buttons_frame, text="Generate", command=self.generate_key)
        generate_btn.pack(side=tk.TOP, pady=(0, 2))
        
        # Copy key button
        copy_btn = tk.Button(key_buttons_frame, text="Copy Key", command=self.copy_key)
        copy_btn.pack(side=tk.TOP)
        
        # Show/Hide key button
        self.show_key_var = tk.BooleanVar()
        show_key_btn = tk.Checkbutton(inner_config, text="Show Key", variable=self.show_key_var, 
                                     command=self.toggle_key_visibility)
        show_key_btn.grid(row=6, column=1, sticky="w", padx=5, pady=5)
        
        # Share the room in person: QR codes for the app's Scan QR
        qr_buttons_frame = tk.Frame(inner_config)
        qr_buttons_frame.grid(row=6, column=2, padx=5, pady=5)
        tk.Button(qr_buttons_frame, text="Key QR", command=self.show_key_qr).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(qr_buttons_frame, text="Room QR", command=self.show_room_qr).pack(side=tk.LEFT)
        
        # Key display area (for easy copying)
        tk.Label(inner_config, text="Share this key:").grid(row=7, column=0, sticky="e", padx=5, pady=5)
        self.key_display = tk.Text(inner_config, height=3, width=35, wrap=tk.WORD, state=tk.DISABLED)
        self.key_display.grid(row=7, column=1, padx=5, pady=5)
        self.update_key_display()
        
        # TLS (optional): pinned to the CA below if given, else publicly trusted CAs; never unverified
        tls_frame = tk.LabelFrame(config_frame, text="TLS (Optional)", font=("Arial", 9, "italic"))
        tls_frame.pack(padx=10, pady=(0, 10), fill=tk.X)
        # Compact on purpose: the connection tab has to fit the 900x800 window
        self.tls_var = tk.BooleanVar(value=False)
        tk.Checkbutton(tls_frame, text="Use TLS", variable=self.tls_var,
                       command=self.toggle_tls).grid(row=0, column=0, sticky="w", padx=5)
        self.ca_status = tk.Label(tls_frame, text="", font=("Arial", 8), fg="gray", anchor="w")
        self.ca_status.grid(row=0, column=1, sticky="ew", padx=5)
        tk.Button(tls_frame, text="Load CA file...", command=self.load_ca_file).grid(row=0, column=2, sticky="e", padx=5, pady=2)
        tls_frame.grid_columnconfigure(1, weight=1)
        self.ca_text = tk.Text(tls_frame, height=2, width=90, font=("Courier", 8))
        self.ca_text.grid(row=1, column=0, columnspan=3, padx=5, pady=(0, 4))
        self.ca_text.bind("<KeyRelease>", lambda e: self.update_ca_status())
        self.update_ca_status()

        # Buttons frame
        buttons_frame = tk.Frame(self.connection_frame)
        buttons_frame.pack(pady=12)
        
        # Save current room button
        save_room_btn = tk.Button(buttons_frame, text="💾 Save Current Room", 
                                 command=self.save_current_room, bg="#2196F3", fg="white",
                                 font=("Arial", 10, "bold"))
        save_room_btn.pack(side=tk.LEFT, padx=5)
        
        # Connect button
        self.connect_btn = tk.Button(buttons_frame, text="🔗 Connect", command=self.connect_mqtt, 
                                   bg="green", fg="white", font=("Arial", 12, "bold"))
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        # Clear fields button
        clear_btn = tk.Button(buttons_frame, text="🗑️ Clear Fields", command=self.clear_connection_fields,
                             bg="#FF9800", fg="white", font=("Arial", 10, "bold"))
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.status_label = tk.Label(self.connection_frame, text="Not connected", fg="red",
                                   font=("Arial", 10, "bold"))
        self.status_label.pack(pady=10)
        
    def setup_chat_tab(self):
        """Setup the chat interface tab"""
        # Main chat frame
        main_frame = tk.Frame(self.chat_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Chat display frame (left side)
        chat_display_frame = tk.Frame(main_frame)
        chat_display_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Chat header with room name
        self.chat_header = tk.Label(chat_display_frame, text="Chat Messages", 
                                   font=("Arial", 12, "bold"), bg="#E3F2FD", relief=tk.RAISED, pady=5)
        self.chat_header.pack(fill=tk.X, pady=(0, 5))
        
        # Chat messages area
        self.chat_display = scrolledtext.ScrolledText(chat_display_frame, state=tk.DISABLED, 
                                                     wrap=tk.WORD, height=20, background=CHAT_BG)
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=5)

        # Line colors: one per palette entry (usernames hash into it), ours, and grey italic system lines
        for i, color in enumerate(USER_COLORS):
            self.chat_display.tag_configure(f"user{i}", foreground=color)
        self.chat_display.tag_configure("mine", foreground=MY_COLOR)
        self._system_font = tkfont.Font(font=self.chat_display.cget("font"))
        self._system_font.configure(slant="italic")
        self.chat_display.tag_configure("system", foreground=SYSTEM_COLOR, font=self._system_font)
        
        # Message input frame
        input_frame = tk.Frame(chat_display_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.message_entry = tk.Entry(input_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message)
        
        send_btn = tk.Button(input_frame, text="Send", command=self.send_message)
        send_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Users list frame (right side)
        users_frame = tk.Frame(main_frame, width=200)
        users_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        users_frame.pack_propagate(False)
        
        tk.Label(users_frame, text="Online Users", font=("Arial", 12, "bold")).pack()
        self.users_listbox = tk.Listbox(users_frame, width=25)
        self.users_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Disconnect button
        disconnect_btn = tk.Button(users_frame, text="Disconnect", command=self.disconnect_mqtt,
                                 bg="red", fg="white")
        disconnect_btn.pack(fill=tk.X, pady=5)
        
        # Add debug button for cleaning users
        debug_btn = tk.Button(users_frame, text="🧹 Clean Users", command=self.force_clean_users,
                             bg="orange", fg="white", font=("Arial", 8))
        debug_btn.pack(fill=tk.X, pady=2)
        
    def setup_rooms_tab(self):
        """Setup the room management tab"""
        title_label = tk.Label(self.rooms_frame, text="Saved Chat Rooms", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=(20, 5))

        # How the saved-rooms file is protected (keyring, passphrase, or locked)
        self.rooms_status_label = tk.Label(self.rooms_frame, text="", font=("Arial", 9),
                                           wraplength=800, justify=tk.LEFT)
        self.rooms_status_label.pack(padx=20, pady=(0, 10))

        # Main container
        main_container = tk.Frame(self.rooms_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Left side - Room list
        left_frame = tk.Frame(main_container)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        tk.Label(left_frame, text="Saved Rooms:", font=("Arial", 12, "bold")).pack(anchor="w")
        
        # Rooms listbox with scrollbar
        listbox_frame = tk.Frame(left_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.rooms_listbox = tk.Listbox(listbox_frame, font=("Arial", 10))
        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.rooms_listbox.yview)
        self.rooms_listbox.config(yscrollcommand=scrollbar.set)
        
        self.rooms_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.rooms_listbox.bind('<<ListboxSelect>>', self.on_room_select)
        
        # Buttons frame
        buttons_frame = tk.Frame(left_frame)
        buttons_frame.pack(fill=tk.X, pady=10)
        
        edit_btn = tk.Button(buttons_frame, text="✏️ Edit", command=self.edit_room,
                           bg="#FF9800", fg="white")
        edit_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        delete_btn = tk.Button(buttons_frame, text="🗑️ Delete", command=self.delete_room,
                             bg="#F44336", fg="white")
        delete_btn.pack(side=tk.LEFT, padx=5)
        
        quick_connect_btn = tk.Button(buttons_frame, text="🚀 Quick Connect", 
                                    command=self.quick_connect_room,
                                    bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        quick_connect_btn.pack(side=tk.RIGHT)
        
        # Right side - Room details
        right_frame = tk.LabelFrame(main_container, text="Room Details", 
                                   font=("Arial", 10, "bold"))
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(20, 0))
        
        # Room details display
        self.room_details = tk.Text(right_frame, height=15, width=40, wrap=tk.WORD, 
                                   state=tk.DISABLED, font=("Arial", 9))
        self.room_details.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Import/Export buttons
        import_export_frame = tk.Frame(right_frame)
        import_export_frame.pack(fill=tk.X, padx=10, pady=10)
        
        export_btn = tk.Button(import_export_frame, text="📤 Export All", 
                             command=self.export_rooms, bg="#9C27B0", fg="white")
        export_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        import_btn = tk.Button(import_export_frame, text="📥 Import", 
                             command=self.import_rooms, bg="#607D8B", fg="white")
        import_btn.pack(side=tk.LEFT)
        
    def save_current_room(self):
        """Save current room configuration"""
        server = self.server_entry.get().strip()
        port = self.port_entry.get().strip()
        channel = self.channel_entry.get().strip()
        username = self.username_entry.get().strip()
        key = self.key_entry.get().strip()
        
        if not all([server, port, channel, username, key]):
            messagebox.showerror("Error", "Please fill in all fields before saving")
            return
            
        # Ask for room name
        room_name = simpledialog.askstring("Save Room", "Enter a name for this room:")
        if not room_name:
            return
            
        # Check if room name already exists
        if room_name in self.saved_rooms:
            if not messagebox.askyesno("Overwrite", f"Room '{room_name}' already exists. Overwrite?"):
                return
                
        # Save room config
        self.saved_rooms[room_name] = {
            "server": server,
            "port": port,
            "channel": channel,
            "username": username,
            "encryption_key": key,
            "mqtt_username": self.mqtt_username_entry.get().strip(),
            "mqtt_password": self.mqtt_password_entry.get().strip(),
            "tls": self.tls_var.get(),
            "ca": self.get_ca(),
            "saved_date": datetime.now().isoformat()
        }
        
        saved = self.save_rooms_to_file()
        self.refresh_rooms_display()
        if saved:
            messagebox.showinfo("Saved", f"Room '{room_name}' saved successfully!")
        
    def load_room_config(self, event=None):
        """Load selected room configuration"""
        selected_room = self.rooms_var.get()
        if not selected_room or selected_room not in self.saved_rooms:
            return
            
        config = self.saved_rooms[selected_room]
        
        # Load into connection fields
        self.server_entry.delete(0, tk.END)
        self.server_entry.insert(0, config["server"])
        
        self.port_entry.delete(0, tk.END)
        self.port_entry.insert(0, config["port"])
        
        self.channel_entry.delete(0, tk.END)
        self.channel_entry.insert(0, config["channel"])
        
        self.username_entry.delete(0, tk.END)
        self.username_entry.insert(0, config["username"])
        
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, config["encryption_key"])
        
        # Load MQTT authentication if present
        self.mqtt_username_entry.delete(0, tk.END)
        self.mqtt_username_entry.insert(0, config.get("mqtt_username", ""))
        
        self.mqtt_password_entry.delete(0, tk.END)
        self.mqtt_password_entry.insert(0, config.get("mqtt_password", ""))
        
        # TLS (rooms saved before TLS support have neither field)
        self.tls_var.set(bool(config.get("tls", False)))
        self.set_ca(config.get("ca", ""))
        
        self.update_key_display()
        messagebox.showinfo("Loaded", f"Room '{selected_room}' configuration loaded!")
        
    def quick_connect_room(self):
        """Quick connect to selected room from rooms tab"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room first")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        
        # Load the room config
        self.rooms_var.set(room_name)
        self.load_room_config()
        
        # Switch to connection tab and connect
        notebook = self.root.children['!notebook']
        notebook.select(0)  # Switch to connection tab
        
        # Connect after a brief delay to allow tab switch
        self.root.after(100, self.connect_mqtt)
        
    def on_room_select(self, event):
        """Handle room selection in rooms list"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        if room_name in self.saved_rooms:
            self.show_room_details(room_name, self.saved_rooms[room_name])
            
    def show_room_details(self, room_name, config):
        """Show room details in the details panel"""
        details = f"Room Name: {room_name}\n\n"
        details += f"Server: {config['server']}\n"
        details += f"Port: {config['port']}\n"
        details += f"Channel: {config['channel']}\n"
        details += f"Chat Username: {config['username']}\n"
        
        # Show MQTT auth status
        mqtt_user = config.get('mqtt_username', '')
        if mqtt_user:
            details += f"MQTT Username: {mqtt_user}\n"
            details += f"MQTT Password: {'*' * len(config.get('mqtt_password', ''))}\n"
        else:
            details += f"MQTT Auth: Anonymous\n"
            
        details += f"Encryption Key: {'*' * len(config['encryption_key'])}\n"
        if config.get("tls"):
            ca = config.get("ca", "")
            try:
                ca_text = tls_config.describe_ca(ca) if ca else "public CAs"
            except Exception:
                ca_text = "invalid CA certificate"
            details += f"TLS: on ({ca_text})\n\n"
        else:
            details += "TLS: off\n\n"
        details += f"Saved: {config.get('saved_date', 'Unknown')}\n"
        
        self.room_details.config(state=tk.NORMAL)
        self.room_details.delete(1.0, tk.END)
        self.room_details.insert(tk.END, details)
        self.room_details.config(state=tk.DISABLED)
        
    def edit_room(self):
        """Edit selected room"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room to edit")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        config = self.saved_rooms[room_name]
        
        # Create edit dialog
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"Edit Room: {room_name}")
        edit_window.geometry("560x430")
        edit_window.transient(self.root)
        edit_window.grab_set()
        
        # Edit form
        tk.Label(edit_window, text="Server:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        server_entry = tk.Entry(edit_window, width=30)
        server_entry.grid(row=0, column=1, padx=5, pady=5)
        server_entry.insert(0, config["server"])
        
        tk.Label(edit_window, text="Port:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        port_entry = tk.Entry(edit_window, width=30)
        port_entry.grid(row=1, column=1, padx=5, pady=5)
        port_entry.insert(0, config["port"])
        
        tk.Label(edit_window, text="Channel:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        channel_entry = tk.Entry(edit_window, width=30)
        channel_entry.grid(row=2, column=1, padx=5, pady=5)
        channel_entry.insert(0, config["channel"])
        
        tk.Label(edit_window, text="Chat Username:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        username_entry = tk.Entry(edit_window, width=30)
        username_entry.grid(row=3, column=1, padx=5, pady=5)
        username_entry.insert(0, config["username"])
        
        tk.Label(edit_window, text="MQTT Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        mqtt_user_entry = tk.Entry(edit_window, width=30)
        mqtt_user_entry.grid(row=4, column=1, padx=5, pady=5)
        mqtt_user_entry.insert(0, config.get("mqtt_username", ""))
        
        tk.Label(edit_window, text="MQTT Password:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        mqtt_pass_entry = tk.Entry(edit_window, width=30, show="*")
        mqtt_pass_entry.grid(row=5, column=1, padx=5, pady=5)
        mqtt_pass_entry.insert(0, config.get("mqtt_password", ""))
        
        tk.Label(edit_window, text="Encryption Key:").grid(row=6, column=0, sticky="e", padx=5, pady=5)
        key_entry = tk.Entry(edit_window, width=30)
        key_entry.grid(row=6, column=1, padx=5, pady=5)
        key_entry.insert(0, config["encryption_key"])
        
        tls_var = tk.BooleanVar(value=bool(config.get("tls", False)))
        tk.Checkbutton(edit_window, text="Use TLS", variable=tls_var).grid(row=7, column=1, sticky="w", padx=5, pady=5)
        tk.Label(edit_window, text="CA (PEM):").grid(row=8, column=0, sticky="ne", padx=5, pady=5)
        ca_box = tk.Text(edit_window, height=4, width=48, font=("Courier", 8))
        ca_box.grid(row=8, column=1, padx=5, pady=5)
        ca_box.insert("1.0", config.get("ca", ""))
        
        def save_changes():
            new_config = {
                "server": server_entry.get().strip(),
                "port": port_entry.get().strip(),
                "channel": channel_entry.get().strip(),
                "username": username_entry.get().strip(),
                "encryption_key": key_entry.get().strip(),
                "mqtt_username": mqtt_user_entry.get().strip(),
                "mqtt_password": mqtt_pass_entry.get().strip(),
                "tls": tls_var.get(),
                "ca": ca_box.get("1.0", tk.END).strip(),
                "saved_date": config.get("saved_date", datetime.now().isoformat())
            }
            tls_settings = self._tls_settings(new_config["tls"], new_config["ca"])
            if tls_settings is None:
                return
            new_config["ca"] = tls_settings[1]
            
            if not all([new_config["server"], new_config["port"], new_config["channel"], 
                       new_config["username"], new_config["encryption_key"]]):
                messagebox.showerror("Error", "Please fill in all fields")
                return
                
            self.saved_rooms[room_name] = new_config
            self.save_rooms_to_file()
            self.refresh_rooms_display()
            edit_window.destroy()
            messagebox.showinfo("Updated", f"Room '{room_name}' updated successfully!")
        
        # Buttons
        button_frame = tk.Frame(edit_window)
        button_frame.grid(row=9, column=0, columnspan=2, pady=20)
        
        tk.Button(button_frame, text="Save Changes", command=save_changes,
                 bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cancel", command=edit_window.destroy,
                 bg="#F44336", fg="white").pack(side=tk.LEFT, padx=5)
        
    def delete_room(self):
        """Delete selected room"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room to delete")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        
        if messagebox.askyesno("Delete Room", f"Are you sure you want to delete room '{room_name}'?"):
            del self.saved_rooms[room_name]
            self.save_rooms_to_file()
            self.refresh_rooms_display()
            messagebox.showinfo("Deleted", f"Room '{room_name}' deleted successfully!")
            
    def _ask_passphrase(self, prompt, confirm=False):
        """Passphrase dialog; confirm=True means choosing a new one (asked twice). None if cancelled."""
        while True:
            passphrase = simpledialog.askstring("Passphrase", prompt, show="*", parent=self.root)
            if passphrase is None or not confirm:
                return passphrase
            if len(passphrase) < MIN_PASSPHRASE:
                messagebox.showerror("Passphrase", f"Use at least {MIN_PASSPHRASE} characters.",
                                     parent=self.root)
                continue
            again = simpledialog.askstring("Passphrase", "Enter the same passphrase again:",
                                           show="*", parent=self.root)
            if again is None:
                return None
            if again == passphrase:
                return passphrase
            messagebox.showerror("Passphrase", "The passphrases didn't match.", parent=self.root)

    def export_rooms(self):
        """Export all rooms to a file, encrypted with a passphrase chosen now"""
        if not self.saved_rooms:
            messagebox.showwarning("No Rooms", "No rooms to export")
            return
            
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Rooms"
        )
        
        if filename:
            passphrase = self._ask_passphrase(
                "Choose a passphrase to protect this export.\n"
                "You'll need it to import the rooms again:", confirm=True)
            if passphrase is None:
                return
            try:
                _write_private(filename, export_rooms_data(self.saved_rooms, passphrase))
                messagebox.showinfo("Exported", f"Rooms exported (encrypted) to {filename}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export: {str(e)}")
                
    def import_rooms(self):
        """Import rooms from a file"""
        from tkinter import filedialog
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import Rooms"
        )
        
        if filename:
            try:
                with open(filename, 'rb') as f:
                    imported_rooms, was_plaintext = import_rooms_data(f.read(), self._ask_passphrase)
                if imported_rooms is None:
                    return
                if was_plaintext and not messagebox.askyesno(
                        "Unencrypted Export",
                        "This export is NOT encrypted (made by an older version of Mcutie Chat): "
                        "anyone who can read the file can see its room keys and broker passwords.\n\n"
                        "Import it anyway? Afterwards, delete the file or replace it with a new "
                        "Export All, which is encrypted.", icon=messagebox.WARNING):
                    return
                
                # Merge with existing rooms
                conflicts = []
                for room_name in imported_rooms:
                    if room_name in self.saved_rooms:
                        conflicts.append(room_name)
                
                if conflicts:
                    message = f"The following rooms already exist:\n{', '.join(conflicts)}\n\nOverwrite them?"
                    if not messagebox.askyesno("Import Conflicts", message):
                        return
                
                self.saved_rooms.update(imported_rooms)
                saved = self.save_rooms_to_file()
                self.refresh_rooms_display()
                if saved:
                    messagebox.showinfo("Imported", f"Successfully imported {len(imported_rooms)} room(s)")
                
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to import: {str(e)}")
                
    def save_rooms_to_file(self):
        """Save rooms to the encrypted file; True if written"""
        try:
            self.saved_rooms = self.room_vault.save(self.saved_rooms, self._ask_passphrase)
            return True
        except Exception as e:
            messagebox.showerror("Save Error", f"Rooms were not saved to disk: {str(e)}")
            return False
        finally:
            self.rooms_status_label.config(text=self.room_vault.describe())
            
    def load_saved_rooms(self):
        """Load rooms from the encrypted file (migrating an old-format file)"""
        try:
            self.saved_rooms = self.room_vault.load(self._ask_passphrase)
        except Exception as e:
            print(f"Failed to load saved rooms: {e}")
            self.saved_rooms = {}
            messagebox.showwarning("Saved Rooms", f"Saved rooms could not be opened: {e}")
        self.refresh_rooms_display()
        self.rooms_status_label.config(text=self.room_vault.describe())
            
    def refresh_rooms_display(self):
        """Refresh the rooms display in both dropdown and listbox"""
        # Update dropdown
        room_names = list(self.saved_rooms.keys())
        self.rooms_dropdown['values'] = room_names
        
        # Update listbox
        self.rooms_listbox.delete(0, tk.END)
        for room_name in sorted(room_names):
            self.rooms_listbox.insert(tk.END, room_name)
            
        # Clear details if no rooms
        if not room_names:
            self.room_details.config(state=tk.NORMAL)
            self.room_details.delete(1.0, tk.END)
            self.room_details.insert(tk.END, "No saved rooms")
            self.room_details.config(state=tk.DISABLED)
        
    def generate_key(self):
        """Generate a new random 256-bit room key (base64url)"""
        key = chat_crypto.generate_key()
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, key)
        self.update_key_display()
        
    def copy_key(self):
        """Copy the encryption key to clipboard"""
        key = self.key_entry.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.root.update()  # Required on some systems
        messagebox.showinfo("Copied", "Encryption key copied to clipboard!")
        
    # ---------------------------------------------------------------- QR exchange
    def _room_fingerprint(self, key, room):
        return chat_crypto.fingerprint(chat_crypto.key_from_input(key, room))

    @staticmethod
    def _qr_version(payload):
        """QR version the payload needs at error-correction level L, or None if it can't fit"""
        import qrcode
        from qrcode.exceptions import DataOverflowError
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(payload)
        try:
            qr.make(fit=True)
        except DataOverflowError:
            return None
        return qr.version

    def show_key_qr(self):
        """Key-only QR (room + key) for people already on the broker"""
        room = self.channel_entry.get().strip()
        key = self.key_entry.get().strip()
        if not room or not key:
            messagebox.showerror("Key QR", "Channel and encryption key are required for a Key QR.")
            return
        self._show_qr_window("Room Key QR Code", "Scan with Mcutie Chat (Scan QR)\nto import this room key",
                             qr_exchange.build_key(room, key), self._room_fingerprint(key, room))

    def show_room_qr(self):
        """Full-room QR (broker, login, TLS, room, key) so a new user can join with one scan"""
        server = self.server_entry.get().strip()
        room = self.channel_entry.get().strip()
        key = self.key_entry.get().strip()
        try:
            port = int(self.port_entry.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Room QR", "Port must be a number from 1 to 65535.")
            return
        if not server or not room or not key:
            messagebox.showerror("Room QR", "Server, channel and encryption key are required for a Room QR.")
            return
        tls_settings = self._tls_settings(self.tls_var.get(), self.get_ca())
        if tls_settings is None:
            return
        tls, ca = tls_settings
        payload = qr_exchange.build_room(server, port, room, key, self.mqtt_username_entry.get().strip(),
                                         self.mqtt_password_entry.get().strip(), tls=tls, ca=ca)
        version = self._qr_version(payload)
        if version is None:
            messagebox.showerror("Room QR", "This room's settings are too large for a QR code.\n\n"
                                            "An EC P-256 CA certificate is much smaller than an RSA one.")
            return
        warning = ("This QR contains the broker password and the room key.\n\n"
                   "Show it only to people you'd give both to.")
        if version > QR_MAX_VERSION:
            warning += (f"\n\nThis QR is large (version {version}) and may not scan reliably from a screen. "
                        "An EC P-256 CA keeps it small.")
        if not messagebox.askyesno("Show Room QR?", warning + "\n\nShow it now?"):
            return
        self._show_qr_window("Room QR Code", "Scan with Mcutie Chat (Scan QR)\nto join this room",
                             payload, self._room_fingerprint(key, room))

    def _show_qr_window(self, title, instructions, payload, fingerprint):
        """QR in a window, built in memory only, with fingerprint and auto-close"""
        import qrcode
        from PIL import Image, ImageTk
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=4)
        qr.add_data(payload)
        qr.make(fit=True)
        # Whole pixels per module: fractional scaling makes modules uneven and unscannable
        modules = qr.modules_count + 2 * qr.border
        px = max(2, 480 // modules)
        img = qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        img = img.resize((modules * px, modules * px), Image.NEAREST)

        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.resizable(False, False)
        tk.Label(win, text=instructions, font=("Arial", 11)).pack(padx=20, pady=(15, 8))
        photo = ImageTk.PhotoImage(img)
        tk.Label(win, image=photo, bd=0).pack(padx=20)
        win.photo = photo  # keep a reference while shown
        tk.Label(win, text=f"Fingerprint: {fingerprint}", font=("Arial", 14, "bold")).pack(pady=(10, 2))
        countdown = tk.Label(win, text=f"Closes in {QR_TIMEOUT} s", fg="gray")
        countdown.pack()
        remaining = [QR_TIMEOUT]
        timer = [None]

        def close():
            if timer[0]:
                win.after_cancel(timer[0])
            win.photo = None
            win.destroy()

        def tick():
            remaining[0] -= 1
            if remaining[0] <= 0:
                close()
                return
            countdown.config(text=f"Closes in {remaining[0]} s")
            timer[0] = win.after(1000, tick)

        tk.Button(win, text="Close", width=12, command=close).pack(pady=12)
        win.protocol("WM_DELETE_WINDOW", close)
        timer[0] = win.after(1000, tick)
        return win

    def import_qr_text(self):
        """Paste a Room/Key QR payload (the text a phone's QR reader shows) and import it"""
        dlg = tk.Toplevel(self.root)
        dlg.title("Import from QR text")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text="Paste the text of a Mcutie Chat Room QR or Key QR\n"
                           "(e.g. read with a phone's camera app):").pack(padx=15, pady=(12, 5))
        box = tk.Text(dlg, height=8, width=70, font=("Courier", 9))
        box.pack(padx=15)
        box.focus_set()

        def do_import():
            text = box.get("1.0", tk.END).strip()
            try:
                data = qr_exchange.parse(text)
            except ValueError as e:
                messagebox.showerror("Import from QR text", str(e), parent=dlg)
                return
            fingerprint = self._room_fingerprint(data["key"], data["room"])
            if data["type"] == qr_exchange.TYPE_ROOM:
                if not data["tls"]:
                    tls_text = "off"
                elif data["ca"]:
                    tls_text = f"on, CA: {tls_config.describe_ca(data['ca'])}"
                else:
                    tls_text = "on, publicly trusted CAs"
                details = (f"Room: {data['room']}\nServer: {data['host']}:{data['port']}\n"
                           f"MQTT user: {data['mqtt_user'] or '(anonymous)'}\nTLS: {tls_text}")
            else:
                details = f"Room key for: {data['room']}"
            if not messagebox.askyesno("Import from QR?", f"{details}\n\nFingerprint: {fingerprint}\n\n"
                                       "Check it matches the other person's screen. Import?", parent=dlg):
                return
            dlg.destroy()
            self._apply_qr_import(data)

        buttons = tk.Frame(dlg)
        buttons.pack(pady=10)
        tk.Button(buttons, text="Import", width=10, command=do_import).pack(side=tk.LEFT, padx=5)
        tk.Button(buttons, text="Cancel", width=10, command=dlg.destroy).pack(side=tk.LEFT, padx=5)
        return dlg

    def _apply_qr_import(self, data):
        """Fill the connection form from a confirmed QR payload"""
        def put(entry, value):
            entry.delete(0, tk.END)
            entry.insert(0, value)
        put(self.channel_entry, data["room"])
        put(self.key_entry, data["key"])
        self.update_key_display()
        if data["type"] == qr_exchange.TYPE_ROOM:
            put(self.server_entry, data["host"])
            put(self.port_entry, str(data["port"]))
            put(self.mqtt_username_entry, data["mqtt_user"])
            put(self.mqtt_password_entry, data["mqtt_pass"])
            self.tls_var.set(data["tls"])
            self.set_ca(data["ca"])
            self.username_entry.delete(0, tk.END)  # the QR never carries a chat name
            messagebox.showinfo("Imported", "Room imported.\n\nEnter your chat username, then Connect.")
            return
        # Key only: offer to update saved rooms that use this channel
        matching = [name for name, cfg in self.saved_rooms.items() if cfg.get("channel") == data["room"]]
        if matching and messagebox.askyesno("Update saved rooms?",
                                            "Also update the key in these saved rooms?\n\n" + "\n".join(matching)):
            for name in matching:
                self.saved_rooms[name]["encryption_key"] = data["key"]
            self.save_rooms_to_file()
            messagebox.showinfo("Imported", f"Key imported and {len(matching)} saved room(s) updated.")
        else:
            messagebox.showinfo("Imported", f"Key imported for channel '{data['room']}'.")

    def toggle_tls(self):
        """Switch the default port when TLS is toggled; leave custom ports alone"""
        port = self.port_entry.get().strip()
        if self.tls_var.get() and port in ("", "1883"):
            self.port_entry.delete(0, tk.END); self.port_entry.insert(0, "8883")
        elif not self.tls_var.get() and port == "8883":
            self.port_entry.delete(0, tk.END); self.port_entry.insert(0, "1883")

    def get_ca(self):
        return self.ca_text.get("1.0", tk.END).strip()

    def set_ca(self, pem):
        self.ca_text.delete("1.0", tk.END)
        if pem:
            self.ca_text.insert("1.0", pem)
        self.update_ca_status()

    def update_ca_status(self):
        """Describe the CA in the box, or say what's wrong with it"""
        pem = self.get_ca()
        if not pem:
            self.ca_status.config(text="Broker CA (PEM) below - leave empty for publicly trusted brokers", fg="gray")
            return
        try:
            self.ca_status.config(text=tls_config.describe_ca(tls_config.validate_ca_pem(pem)), fg="dark green")
        except Exception as e:
            self.ca_status.config(text=f"Invalid CA: {e}", fg="red")

    def load_ca_file(self):
        """Read a CA certificate file into the CA box"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Broker CA certificate",
                                          filetypes=[("Certificates", "*.pem *.crt *.cer"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path) as f:
                self.set_ca(tls_config.validate_ca_pem(f.read()))
        except Exception as e:
            messagebox.showerror("CA certificate", f"Couldn't load the CA certificate:\n{e}")

    def _tls_settings(self, tls, ca):
        """(tls, normalized ca) or None after showing an error"""
        if ca and not tls:
            messagebox.showerror("TLS", "Turn on TLS to use a CA certificate.")
            return None
        if ca:
            try:
                ca = tls_config.validate_ca_pem(ca)
            except ValueError as e:
                messagebox.showerror("TLS", f"Invalid CA certificate:\n{e}")
                return None
        return tls, ca

    def toggle_mqtt_password_visibility(self):
        """Toggle showing/hiding the MQTT password"""
        if self.show_mqtt_password_var.get():
            self.mqtt_password_entry.config(show="")
        else:
            self.mqtt_password_entry.config(show="*")
            
    def toggle_key_visibility(self):
        """Toggle showing/hiding the key in the entry field"""
        if self.show_key_var.get():
            self.key_entry.config(show="")
        else:
            self.key_entry.config(show="*")
            
    def update_key_display(self):
        """Update the key display area"""
        key = self.key_entry.get()
        self.key_display.config(state=tk.NORMAL)
        self.key_display.delete(1.0, tk.END)
        self.key_display.insert(tk.END, key)
        self.key_display.config(state=tk.DISABLED)
        
        # Bind key entry changes to update display
        self.key_entry.bind('<KeyRelease>', lambda e: self.update_key_display())
        
    def connect_mqtt(self):
        """Connect to MQTT broker"""
        try:
            # Get connection details
            server = self.server_entry.get().strip()
            port = int(self.port_entry.get().strip())
            self.channel = self.channel_entry.get().strip()
            self.username = self.username_entry.get().strip()
            encryption_key = self.key_entry.get().strip()
            
            # Get MQTT authentication (optional)
            mqtt_username = self.mqtt_username_entry.get().strip()
            mqtt_password = self.mqtt_password_entry.get().strip()
            
            if not all([server, self.channel, self.username, encryption_key]):
                messagebox.showerror("Error", "Please fill in all required fields")
                return
            tls_settings = self._tls_settings(self.tls_var.get(), self.get_ca())
            if tls_settings is None:
                return
            use_tls, ca_pem = tls_settings
                
            # Setup encryption: generated keys are used directly, passphrases go through scrypt
            self.key = chat_crypto.key_from_input(encryption_key, self.channel)
            
            # Setup topics
            self.messages_topic = f"chat/{self.channel}/messages"
            self.presence_topic = f"chat/{self.channel}/presence"
            self.userlist_topic = f"chat/{self.channel}/users"
            
            # Setup MQTT client. Random client ID per connection (never derived from the name
            # or room), so people sharing a room QR - or a stale client - never collide.
            self.client_id = "mqttchat-" + secrets.token_hex(8)
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=self.client_id)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            # Set MQTT authentication if provided
            if mqtt_username:
                self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
                self.add_system_message(f"Using MQTT authentication for user: {mqtt_username}")
            else:
                self.add_system_message("Connecting with anonymous MQTT access")
            
            # TLS: pinned to the room's CA if it has one, else the certifi list; never unverified
            if use_tls:
                self.mqtt_client.tls_set_context(tls_config.make_ssl_context(ca_pem or None))
                self.add_system_message("Using TLS" + (" (pinned CA)" if ca_pem else " (public CAs)"))

            # Set last will (sent when we disconnect unexpectedly)
            will_msg = json.dumps({"user": self.username, "status": "offline", "timestamp": time.time()})
            self.mqtt_client.will_set(f"{self.presence_topic}/{self.username}", will_msg, retain=True)
            
            # Connect
            self.status_label.config(text="Connecting...", fg="orange")
            self.mqtt_client.connect(server, port, 60)
            self.mqtt_client.loop_start()
            
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")
            self.status_label.config(text="Connection failed", fg="red")
            
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Called when MQTT connects - ENHANCED VERSION"""
        if rc == 0:
            self.connected = True
            self.status_label.config(text="Connected", fg="green")
            
            # ENHANCED CLEANUP
            self.clear_my_presence()
            time.sleep(0.2)  # Give time for clearing
            
            # Clear our local user list
            self.online_users.clear()
            self.recent_joins.clear()  # Clear join tracking
            self.update_users_list()
            
            # Subscribe to topics
            client.subscribe(self.messages_topic)
            client.subscribe(f"{self.presence_topic}/+")
            
            # Announce our presence
            self.announce_presence("online")
            
            # Start heartbeat
            self.start_heartbeat()
            
            # Update chat header with room name
            self.chat_header.config(text=f"Chat Messages - #{self.channel}")
            
            # Add welcome message
            self.add_system_message("Connected to chat!")
            self.add_system_message(f"Room key fingerprint: {chat_crypto.fingerprint(self.key)}")
            
        else:
            self.status_label.config(text=f"Connection failed (code {rc})", fg="red")
            
    def on_mqtt_message(self, client, userdata, msg):
        """Called when MQTT message received"""
        try:
            topic = msg.topic
            payload = msg.payload.decode()
            
            if topic == self.messages_topic:
                self.handle_chat_message(payload)
            elif topic.startswith(self.presence_topic):
                self.handle_presence_message(topic, payload)
                
        except Exception as e:
            print(f"Error handling message: {e}")
            
    def on_mqtt_disconnect(self, client, userdata, rc):
        """Called when MQTT disconnects"""
        self.connected = False
        self.status_label.config(text="Disconnected", fg="red")
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            
    def handle_chat_message(self, encrypted_payload):
        """Handle incoming chat message"""
        try:
            # Decrypt message (AES-256-GCM, bound to this room's topic)
            decrypted_data = chat_crypto.decrypt(self.key, encrypted_payload, self.messages_topic)
            message_data = json.loads(decrypted_data.decode())
            
            username = message_data.get("user", "Unknown")
            message = message_data.get("message", "")
            timestamp = message_data.get("timestamp", time.time())
            
            # Don't show our own messages (we already displayed them)
            if username != self.username:
                self.add_chat_message(username, message, timestamp)
                
        except Exception as e:
            print(f"Error decrypting message: {e}")
            
    def handle_presence_message(self, topic, payload):
        """Handle user presence updates - ANTI-SPAM DUPLICATE PREVENTION"""
        try:
            # Extract username from topic path
            user_from_topic = topic.split('/')[-1]
            
            # Handle empty payload (user leaving/clearing presence)
            if not payload.strip():
                # Remove user from list if present
                if user_from_topic in self.online_users:
                    self.online_users.remove(user_from_topic)
                    if user_from_topic != self.username:
                        self.add_system_message(f"{user_from_topic} left the chat")
                    # Clear from recent joins when they leave
                    if user_from_topic in self.recent_joins:
                        del self.recent_joins[user_from_topic]
                self.update_users_list()
                return
            
            # Parse the JSON payload
            data = json.loads(payload)
            user = data.get("user", "")
            status = data.get("status", "")
            
            # Validate that topic user matches payload user
            if user != user_from_topic:
                print(f"Warning: User mismatch - topic: {user_from_topic}, payload: {user}")
                return
            
            # ANTI-SPAM DUPLICATE PREVENTION
            if status == "online":
                # Check if user is already in the list
                was_already_online = user in self.online_users
                
                # Add user to list (set automatically prevents duplicates)
                self.online_users.add(user)
                
                # Anti-spam: Only announce if it's a NEW join AND we haven't announced recently
                current_time = time.time()
                last_join_time = self.recent_joins.get(user, 0)
                
                # Only announce if: 1) Not already online, 2) Not ourselves, 3) Haven't announced in last 60 seconds
                if (not was_already_online and 
                    user != self.username and 
                    current_time - last_join_time > 60):
                    
                    self.add_system_message(f"{user} joined the chat")
                    self.recent_joins[user] = current_time
                    
            elif status == "offline":
                # Remove user if present
                if user in self.online_users:
                    self.online_users.remove(user)
                    if user != self.username:
                        self.add_system_message(f"{user} left the chat")
                    # Clear from recent joins when they leave
                    if user in self.recent_joins:
                        del self.recent_joins[user]
            
            # Update the display
            self.update_users_list()
            
        except json.JSONDecodeError:
            print(f"Invalid JSON in presence message: {payload}")
        except Exception as e:
            print(f"Error handling presence: {e}")
            
    def send_message(self, event=None):
        """Send a chat message"""
        if not self.connected:
            return
            
        message_text = self.message_entry.get().strip()
        if not message_text:
            return
            
        try:
            # Create message data
            message_data = {
                "user": self.username,
                "message": message_text,
                "timestamp": time.time()
            }
            
            # Encrypt message (AES-256-GCM, bound to this room's topic)
            json_data = json.dumps(message_data)
            encrypted_payload = chat_crypto.encrypt(self.key, json_data.encode(), self.messages_topic)
            
            # Publish to MQTT
            self.mqtt_client.publish(self.messages_topic, encrypted_payload)
            
            # Add to our own chat display
            self.add_chat_message(self.username, message_text, message_data["timestamp"])
            
            # Clear input
            self.message_entry.delete(0, tk.END)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send message: {str(e)}")
            
    def announce_presence(self, status):
        """Announce our online/offline status"""
        if self.mqtt_client and self.connected:
            presence_data = {
                "user": self.username,
                "status": status,
                "timestamp": time.time()
            }
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", 
                                   json.dumps(presence_data), retain=True)
            
    def start_heartbeat(self):
        """Start sending periodic heartbeat to show we're online"""
        if self.connected:
            self.announce_presence("online")
            # Schedule next heartbeat in 30 seconds
            self.heartbeat_timer = threading.Timer(30.0, self.start_heartbeat)
            self.heartbeat_timer.start()
            
    def disconnect_mqtt(self):
        """Disconnect from MQTT"""
        def _disconnect_worker():
            """Worker function to handle disconnect in background"""
            try:
                if self.connected and self.mqtt_client:
                    # Announce offline status
                    self.announce_presence("offline")
                    time.sleep(0.5)  # Give time for message to send
                    self.clear_my_presence()  # Clear our retained presence
                    
                    # Disconnect, then stop the loop (in this order the DISCONNECT packet is
                    # actually sent, so the broker doesn't fire our Last Will)
                    self.mqtt_client.disconnect()
                    self.mqtt_client.loop_stop()
                    
                # Cancel heartbeat timer
                if self.heartbeat_timer:
                    self.heartbeat_timer.cancel()
                    self.heartbeat_timer = None
                    
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                # Update GUI in main thread
                self.root.after(0, self._finish_disconnect)
        
        # Update status immediately. Don't clear self.connected here: the worker checks it to
        # decide whether to disconnect (clearing it first left the old client running);
        # _finish_disconnect and on_mqtt_disconnect reset it afterwards.
        self.status_label.config(text="Disconnecting...", fg="orange")
        
        # Run disconnect in background thread to avoid GUI freeze
        disconnect_thread = threading.Thread(target=_disconnect_worker, daemon=True)
        disconnect_thread.start()
        
    def _finish_disconnect(self):
        """Finish disconnect process in main GUI thread"""
        self.connected = False
        self.online_users.clear()
        self.recent_joins.clear()  # Clear join tracking
        self.update_users_list()
        self.add_system_message("Disconnected from chat")
        self.status_label.config(text="Disconnected", fg="red")
        
        # Reset chat header
        self.chat_header.config(text="Chat Messages")
        
    def add_chat_message(self, username, message, timestamp):
        """Add a chat message to the display"""
        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        
        self.chat_display.config(state=tk.NORMAL)
        tag = "mine" if username == self.username else f"user{user_color_index(username)}"
        self.chat_display.insert(tk.END, f"[{time_str}] {username}: {message}\n", tag)
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def add_system_message(self, message):
        """Add a system message to the display"""
        time_str = datetime.now().strftime("%H:%M:%S")
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"[{time_str}] *** {message} ***\n", "system")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def update_users_list(self):
        """Update the online users list"""
        self.users_listbox.delete(0, tk.END)
        for user in sorted(self.online_users):
            self.users_listbox.insert(tk.END, user)
            
    def on_closing(self):
        """Handle window closing"""
        def _cleanup_and_exit():
            """Cleanup function that runs in background"""
            try:
                if self.connected and self.mqtt_client:
                    self.announce_presence("offline")
                    time.sleep(0.5)  # Give time for message to send
                    self.clear_my_presence()  # Clear our retained presence
                    self.mqtt_client.disconnect()
                    self.mqtt_client.loop_stop()
                if self.heartbeat_timer:
                    self.heartbeat_timer.cancel()
            except:
                pass  # Ignore errors during cleanup
            finally:
                # Destroy window in main thread
                self.root.after(0, self.root.destroy)
        
        # (self.connected stays as it is: the cleanup thread checks it to decide whether to
        # announce offline and disconnect)
        
        # Run cleanup in background thread
        cleanup_thread = threading.Thread(target=_cleanup_and_exit, daemon=True)
        cleanup_thread.start()
        
        # Give a short timeout for cleanup, then force close
        self.root.after(1000, self.root.destroy)
        
    def run(self):
        """Start the application"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

def _self_test():
    """python mqchat.py --self-test: saved-rooms storage, exports and chat colors (no GUI, no real
    keyring: an in-memory one stands in; files go to a temporary folder)."""
    import tempfile

    class MemKeyring:
        def __init__(self):
            self.store = {}
        def get_password(self, service, user):
            return self.store.get((service, user))
        def set_password(self, service, user, password):
            self.store[(service, user)] = password

    class NullKeyring:  # accepts writes but keeps nothing, like keyring's null backend
        def get_password(self, service, user):
            return None
        def set_password(self, service, user, password):
            pass

    def answers(*replies):
        """A fake passphrase dialog: returns replies in order, records the prompts it got."""
        queue = list(replies)
        def ask(prompt, confirm):
            ask.prompts.append((prompt, confirm))
            assert queue, f"unexpected passphrase prompt: {prompt!r}"
            return queue.pop(0)
        ask.prompts = []
        return ask

    def never(prompt, confirm):
        raise AssertionError(f"unexpected passphrase prompt: {prompt!r}")

    def raw(path):
        with open(path, "rb") as f:
            return f.read()

    def raises(fn, exc=RoomsFileError):
        try:
            fn()
        except exc:
            return
        raise AssertionError(f"{fn} did not raise {exc.__name__}")

    rooms = {
        "Home": {"server": "broker.example", "port": "8883", "channel": "general", "username": "me",
                 "encryption_key": chat_crypto.generate_key(), "mqtt_username": "u",
                 "mqtt_password": "secret-pw", "tls": True, "ca": "", "saved_date": "2026-01-01T00:00:00"},
        "Work ☕": {"server": "10.0.0.2", "port": "1883", "channel": "team", "username": "me",
                   "encryption_key": "a passphrase key", "tls": False, "ca": ""},
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "mqtt_chat_rooms.json")

        def write_legacy(data):
            with open(path, "wb") as f:
                f.write(_legacy_fernet().encrypt(json.dumps(data).encode()))

        def check_not_plaintext():
            data = raw(path)
            for secret in (b"secret-pw", rooms["Home"]["encryption_key"].encode(), b"broker.example"):
                assert secret not in data, "secret in plaintext on disk"
            raises(lambda: _legacy_fernet().decrypt(data), Exception)  # old format is gone
            assert not os.path.exists(path + ".tmp")

        # 1. Old fixed-key Fernet file migrates silently to keyring AES-GCM, rooms intact
        write_legacy(rooms)
        kr = MemKeyring()
        vault = RoomVault(path, kr)
        assert vault.load(never) == rooms
        assert vault.mode == "keyring" and not vault.legacy_pending and not vault.locked
        env = json.loads(raw(path))
        assert (env["format"], env["version"], env["kdf"]) == (ROOMS_FORMAT, ROOMS_VERSION, "keyring")
        check_not_plaintext()
        data_key = chat_crypto.parse_raw_key(kr.store[(KEYRING_SERVICE, KEYRING_ENTRY)])
        assert len(data_key) == 32

        # 2. save -> load round trip; the data key is made once and reused
        assert RoomVault(path, kr).load(never) == rooms
        changed = dict(rooms, Extra={"server": "x", "port": "1", "channel": "c", "username": "n",
                                     "encryption_key": "k"})
        v = RoomVault(path, kr)
        v.load(never)
        v.save(changed, never)
        assert RoomVault(path, kr).load(never) == changed
        assert chat_crypto.parse_raw_key(kr.store[(KEYRING_SERVICE, KEYRING_ENTRY)]) == data_key
        first_nonce = json.loads(raw(path))["nonce"]
        v.save(changed, never)
        assert json.loads(raw(path))["nonce"] != first_nonce  # fresh nonce on every write

        # 3. A tampered file, a header edit, a missing or different keyring key: locked, never overwritten
        good = raw(path)
        env = json.loads(good)
        ct = bytearray(base64.b64decode(env["ct"])); ct[0] ^= 1
        for bad_env in (dict(env, ct=base64.b64encode(bytes(ct)).decode()), dict(env, extra=1)):
            with open(path, "wb") as f:
                f.write(json.dumps(bad_env).encode())
            before = raw(path)
            v = RoomVault(path, kr)
            raises(lambda: v.load(never))
            assert v.locked
            raises(lambda: v.save(rooms, never))
            assert raw(path) == before
        with open(path, "wb") as f:
            f.write(good)
        for other in (MemKeyring(), None):   # key absent / no keyring at all
            v = RoomVault(path, other)
            raises(lambda: v.load(never))
            raises(lambda: v.save(rooms, never))
            assert raw(path) == good
        other = MemKeyring()
        other.set_password(KEYRING_SERVICE, KEYRING_ENTRY, chat_crypto.generate_key())
        v = RoomVault(path, other)
        raises(lambda: v.load(never))
        raises(lambda: v.save(rooms, never))
        assert raw(path) == good
        damaged = MemKeyring()
        damaged.set_password(KEYRING_SERVICE, KEYRING_ENTRY, "not a key")
        raises(lambda: RoomVault(path, damaged).load(never))
        with open(path, "wb") as f:
            f.write(b"neither format")
        raises(lambda: RoomVault(path, kr).load(never))

        # 4. No keyring: migrate with a new passphrase, unlock next session, wrong one retried
        for no_keyring in (None, NullKeyring()):
            write_legacy(rooms)
            ask = answers("correct horse battery")
            v = RoomVault(path, no_keyring)
            assert v.load(ask) == rooms and ask.prompts[0][1] is True   # chose a new one
            assert v.mode == "passphrase" and not v.legacy_pending
            env = json.loads(raw(path))
            assert env["kdf"] == "scrypt" and env["n"] == PASS_SCRYPT_N
            check_not_plaintext()
            v.save(changed, never)              # same session: no prompt again
            ask = answers("wrong", "correct horse battery")
            v = RoomVault(path, no_keyring)
            assert v.load(ask) == changed and len(ask.prompts) == 2
            assert "Wrong passphrase" in ask.prompts[1][0]
            assert json.loads(raw(path))["salt"] == env["salt"]

        # 5. No keyring, migration passphrase cancelled: rooms still usable, old file kept untouched
        write_legacy(rooms)
        before = raw(path)
        v = RoomVault(path, None)
        assert v.load(answers(None)) == rooms and v.legacy_pending
        assert raw(path) == before and "old" in v.describe()
        raises(lambda: v.save(rooms, answers(None)))
        assert raw(path) == before
        v.save(rooms, answers("another passphrase"))
        assert not v.legacy_pending and RoomVault(path, None).load(answers("another passphrase")) == rooms

        # 6. No keyring, unlock cancelled: locked; saving asks again and merges, never clobbers
        before = raw(path)
        v = RoomVault(path, None)
        assert v.load(answers(None)) == {} and v.locked
        new = {"New": {"server": "s", "port": "1", "channel": "c", "username": "n", "encryption_key": "k"}}
        raises(lambda: v.save(new, answers(None)))
        assert raw(path) == before
        merged = v.save(new, answers("another passphrase"))
        assert merged == {**rooms, **new} and not v.locked
        assert RoomVault(path, None).load(answers("another passphrase")) == merged

        # 7. Never plaintext: a new file with no keyring and no passphrase is not written at all
        os.remove(path)
        v = RoomVault(path, None)
        assert v.load(never) == {}
        raises(lambda: v.save(rooms, answers(None)))
        assert not os.path.exists(path)

        # 8. A passphrase file moves to the keyring once one is available
        RoomVault(path, None).save(rooms, answers("passphrase file"))
        kr2 = MemKeyring()
        v = RoomVault(path, kr2)
        assert v.load(answers("passphrase file")) == rooms and v.mode == "keyring"
        assert json.loads(raw(path))["kdf"] == "keyring"
        assert RoomVault(path, kr2).load(never) == rooms

        # 9. Exports: passphrase-encrypted round trip, wrong passphrase, tampering, old plaintext
        blob = export_rooms_data(rooms, "export passphrase")
        assert b"secret-pw" not in blob and json.loads(blob)["format"] == EXPORT_FORMAT
        ask = answers("nope", "export passphrase")
        assert import_rooms_data(blob, ask) == (rooms, False) and len(ask.prompts) == 2
        assert import_rooms_data(blob, answers(None)) == (None, False)
        env = json.loads(blob)
        assert import_rooms_data(json.dumps(dict(env, n=2 ** 16)).encode(),   # header is authenticated
                                 answers("export passphrase", None)) == (None, False)
        assert import_rooms_data(json.dumps(rooms).encode(), never) == (rooms, True)
        assert import_rooms_data(b"\xef\xbb\xbf" + json.dumps(rooms).encode(), never) == (rooms, True)
        raises(lambda: import_rooms_data(b"[1, 2]", never))
        raises(lambda: import_rooms_data(raw(path), never))   # a saved-rooms file isn't an export
        raises(lambda: import_rooms_data(b"\x00junk", never))

    # 10. Chat colors: stable, readable on the chat background, ours distinct
    def luminance(hex_color):
        def channel(c):
            c /= 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    bg = luminance(CHAT_BG)
    for color in USER_COLORS + (MY_COLOR, SYSTEM_COLOR):
        ratio = (bg + 0.05) / (luminance(color) + 0.05)
        assert ratio >= 4.5, f"{color} contrast {ratio:.2f}"
    assert len(set(USER_COLORS)) == len(USER_COLORS) >= 8 and MY_COLOR not in USER_COLORS
    names = [f"user{i}" for i in range(200)] + ["alice", "Bob", "ünïcode"]
    indexes = [user_color_index(n) for n in names]
    assert indexes == [user_color_index(n) for n in names]
    assert all(0 <= i < len(USER_COLORS) for i in indexes) and len(set(indexes)) == len(USER_COLORS)
    assert user_color_index("alice") == int(hashlib.sha256(b"alice").hexdigest()[:8], 16) % len(USER_COLORS)
    print("mqchat self-tests passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
        sys.exit(0)
    # Check for required packages
    try:
        import paho.mqtt.client as mqtt
        from cryptography.fernet import Fernet
        import qrcode, certifi, keyring  # noqa: F401
        from PIL import Image, ImageTk  # noqa: F401
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("\nPlease install required packages:")
        print("pip install paho-mqtt cryptography qrcode pillow certifi keyring")
        input("Press Enter to exit...")
        exit(1)
        
    app = SecureMQTTChat()
    app.run()