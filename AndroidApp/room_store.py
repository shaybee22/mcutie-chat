"""Saved rooms: where they live and how they're protected (no Kivy imports).

Rooms live in <user_data_dir>/rooms. On Android that is files/rooms, next to
files/app: python-for-android deletes files/app whenever an updated APK first
starts, so rooms kept there (the old ./rooms) were lost on every update.

Android (needs API 30+):
- A wrapping key in the Android Keystore (alias mcutiechat-rooms-kek, AES-256-GCM,
  non-exportable) that needs a fresh strong-biometric or screen-lock prompt for
  every single use (timeout 0, bound to the Cipher through a CryptoObject).
  Unlocking the phone does not count.
- A random 256-bit data key, stored only wrapped by that key in datakey.bin:
      0x01 || 12-byte IV || AES-GCM(data key) + tag,  AAD "mcutiechat-datakey"
  After one prompt it is held in memory (never on disk unwrapped) until lock():
  the app calls that when it goes to the background or closes.
- Each room is <16 random hex>.room:
      0x02 || 12-byte nonce || AES-256-GCM(JSON) + tag,  AAD "mcutiechat-room:<file id>"
  over {"name": <room name>, "room": {...saved fields...}}, encrypted with the
  data key. Room names are inside the ciphertext, so nothing is listed while locked.
- Version 0x01 room files are the earlier format (encrypted directly by the
  5-minute Keystore key mcutiechat-rooms). They are migrated to 0x02 after the
  first unlock, then that old key is deleted.

Desktop and other non-Android runs: no Keystore. The Kivy desktop build is for
development (the real desktop client is ../mqchat.py), so rooms stay plaintext
<name>.json files there, as before. Nothing ever locks.

Never put room contents, keys or passwords into exceptions, prints or logs:
error messages here are fixed strings.
"""
import json
import os
import secrets

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
except ImportError:  # desktop plaintext fallback doesn't need it
    AESGCM = None
    InvalidTag = Exception

VERSION = 2          # room files encrypted with the data key
VERSION_V1 = 1       # earlier room files, encrypted by the old 5-minute Keystore key
NONCE_SIZE = 12
TAG_SIZE = 16
DATA_KEY_SIZE = 32
AAD_PREFIX = b"mcutiechat-room:"
DATAKEY_FILE = "datakey.bin"
DATAKEY_VERSION = 1
DATAKEY_AAD = b"mcutiechat-datakey"
ROOM_EXT = ".room"
PLAIN_EXT = ".json"
TMP_EXT = ".tmp"


class RoomStoreError(Exception):
    """Saved-rooms error with a fixed, non-secret message."""


class LockedError(RoomStoreError):
    def __init__(self):
        super().__init__("Saved rooms are locked.")


class InvalidatedError(RoomStoreError):
    def __init__(self):
        super().__init__("Saved rooms can't be decrypted: their key is gone.")


class NoScreenLockError(RoomStoreError):
    def __init__(self):
        super().__init__("Set a screen lock to save rooms.")


class _BadFile(RoomStoreError):
    """One file failed to decrypt or parse (damaged, renamed or swapped)."""


def valid_name(name):
    """True if name is safe as a plaintext file name (desktop backend)."""
    return (isinstance(name, str) and name.strip() == name and name not in ("", ".", "..")
            and not any(c in name for c in "/\\\0"))


def _write_atomic(path, data):
    tmp = path + TMP_EXT
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RoomStoreError("Could not write the saved room file.")


def _read_plain(path):
    """Read a plaintext room .json; returns a dict or None if unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _plain_files(folder):
    try:
        return sorted(f for f in os.listdir(folder) if f.endswith(PLAIN_EXT))
    except OSError:
        return []


class PlainStore:
    """Desktop/dev fallback: plaintext <name>.json, same format as before."""
    encrypted = False

    def __init__(self, folder, legacy_dir=None):
        self.folder = folder
        self.notes = []
        if legacy_dir and os.path.isdir(legacy_dir) and \
                os.path.realpath(legacy_dir) != os.path.realpath(folder):
            for fname in _plain_files(legacy_dir):
                name = fname[:-len(PLAIN_EXT)]
                src = os.path.join(legacy_dir, fname)
                if not valid_name(name) or os.path.exists(self._path(name)):
                    continue  # already have one of that name: leave the old file alone
                data = _read_plain(src)
                if data is None:
                    self.notes.append(f"Could not move old saved room file {fname}.")
                    continue
                try:
                    self.save(name, data)
                    os.remove(src)
                except (RoomStoreError, OSError):
                    self.notes.append(f"Could not move old saved room file {fname}.")

    def _path(self, name):
        if not valid_name(name):
            raise RoomStoreError("Invalid room name (no slashes, and not . or ..).")
        return os.path.join(self.folder, name + PLAIN_EXT)

    def is_locked(self):
        return False

    def lock(self):
        pass

    def begin_unlock(self):
        raise RoomStoreError("Nothing to unlock.")

    def finish_unlock(self, cipher):
        raise RoomStoreError("Nothing to unlock.")

    def list_rooms(self):
        return [f[:-len(PLAIN_EXT)] for f in _plain_files(self.folder)]

    def load(self, name):
        data = _read_plain(self._path(name))
        if data is None:
            raise RoomStoreError("Could not read that saved room.")
        return data

    def save(self, name, data):
        _write_atomic(self._path(name), json.dumps(data, indent=2).encode("utf-8"))

    def delete(self, name):
        try:
            os.remove(self._path(name))
        except FileNotFoundError:
            raise RoomStoreError("That saved room no longer exists.")
        except OSError:
            raise RoomStoreError("Could not delete that saved room.")

    def clear_all(self):
        for fname in _plain_files(self.folder):
            try:
                os.remove(os.path.join(self.folder, fname))
            except OSError:
                pass


class EncryptedStore:
    """Android: data key wrapped by a per-use Keystore key (see module docstring).

    keystore must provide:
      has_kek(), create_kek(), delete_kek()
      prepare_wrap() -> cipher, prepare_unwrap(iv) -> cipher   (before the prompt)
      cipher_iv(cipher) -> bytes, finish(cipher, aad, data) -> bytes   (after it)
      has_old_key(), delete_old_key(), old_decrypt(aad, nonce, ct) -> bytes
    raising LockedError / InvalidatedError / NoScreenLockError / _BadFile.
    """
    encrypted = True

    def __init__(self, folder, keystore, legacy_dir=None):
        self.folder = folder
        self.keystore = keystore
        self.legacy_dir = legacy_dir
        self.data_key = None   # bytearray while unlocked
        self.index = None      # name -> file id, while unlocked
        self.pending = None    # (cipher, wrapped data key or None) between begin/finish_unlock
        self.notes = []

    # ---- files
    def _room_files(self):
        try:
            return sorted(f[:-len(ROOM_EXT)] for f in os.listdir(self.folder) if f.endswith(ROOM_EXT))
        except OSError:
            return []

    def _path(self, fid):
        return os.path.join(self.folder, fid + ROOM_EXT)

    def _datakey_path(self):
        return os.path.join(self.folder, DATAKEY_FILE)

    def _read_blob(self, fid):
        try:
            with open(self._path(fid), "rb") as f:
                blob = f.read()
        except OSError:
            raise _BadFile("Could not read a saved room file.")
        if len(blob) < 1 + NONCE_SIZE + TAG_SIZE or blob[0] not in (VERSION, VERSION_V1):
            raise _BadFile("Unknown saved room file format.")
        return blob

    @staticmethod
    def _parse(plain):
        try:
            obj = json.loads(plain.decode("utf-8"))
            name, room = obj["name"], obj["room"]
            if not isinstance(name, str) or not isinstance(room, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise _BadFile("Damaged saved room file.")
        return name, room

    def _aad(self, fid):
        return AAD_PREFIX + fid.encode("ascii")

    def _decrypt_v2(self, fid, blob):
        try:
            plain = AESGCM(bytes(self.data_key)).decrypt(
                blob[1:1 + NONCE_SIZE], blob[1 + NONCE_SIZE:], self._aad(fid))
        except InvalidTag:
            raise _BadFile("Saved room file failed authentication.")
        return self._parse(plain)

    def _decrypt_file(self, fid):
        blob = self._read_blob(fid)
        if blob[0] != VERSION:
            raise _BadFile("Old-format saved room file.")
        return self._decrypt_v2(fid, blob)

    def _encrypt_file(self, fid, name, room):
        plain = json.dumps({"name": name, "room": room}).encode("utf-8")
        nonce = os.urandom(NONCE_SIZE)
        ct = AESGCM(bytes(self.data_key)).encrypt(nonce, plain, self._aad(fid))
        _write_atomic(self._path(fid), bytes([VERSION]) + nonce + ct)

    # ---- lock state
    def is_locked(self):
        return self.data_key is None

    def lock(self):
        if self.data_key is not None:
            for i in range(len(self.data_key)):
                self.data_key[i] = 0
        self.data_key = None
        self.index = None
        # self.pending is kept: it holds no secret, and the PIN screen of a prompt
        # that is still open can pause the app.

    def _nothing_saved(self):
        return not (os.path.exists(self._datakey_path()) or self._room_files()
                    or _plain_files(self.folder)
                    or (self.legacy_dir and _plain_files(self.legacy_dir)))

    def _require_unlocked(self):
        if self.data_key is None:
            raise LockedError()

    def begin_unlock(self):
        """Prepare the Keystore cipher for the prompt. Returns it (Java Cipher)."""
        self.pending = None
        path = self._datakey_path()
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    blob = f.read()
            except OSError:
                raise RoomStoreError("Could not read the saved rooms key file.")
            if len(blob) != 1 + NONCE_SIZE + DATA_KEY_SIZE + TAG_SIZE or blob[0] != DATAKEY_VERSION:
                raise RoomStoreError("The saved rooms key file is damaged.")
            if not self.keystore.has_kek():
                raise InvalidatedError()  # wrapped key with no Keystore key: can never open
            cipher = self.keystore.prepare_unwrap(blob[1:1 + NONCE_SIZE])
            self.pending = (cipher, blob[1 + NONCE_SIZE:])
            return cipher
        if any(self._read_version(fid) == VERSION for fid in self._room_files()):
            raise InvalidatedError()  # data-key files without a data key: can never open
        if not self.keystore.has_kek():
            self.keystore.create_kek()
        cipher = self.keystore.prepare_wrap()
        self.pending = (cipher, None)
        return cipher

    def _read_version(self, fid):
        try:
            with open(self._path(fid), "rb") as f:
                first = f.read(1)
        except OSError:
            return None
        return first[0] if first else None

    def finish_unlock(self, cipher):
        """After a successful prompt: unwrap (or create and wrap) the data key, then
        build the room list and migrate older files."""
        if self.pending is None or self.pending[0] is not cipher:
            raise RoomStoreError("Unlock expired. Try again.")
        _, wrapped = self.pending
        self.pending = None
        if wrapped is not None:
            key = self.keystore.finish(cipher, DATAKEY_AAD, wrapped)
            if len(key) != DATA_KEY_SIZE:
                raise RoomStoreError("The saved rooms key file is damaged.")
        else:
            key = secrets.token_bytes(DATA_KEY_SIZE)
            wrapped = self.keystore.finish(cipher, DATAKEY_AAD, key)
            iv = self.keystore.cipher_iv(cipher)
            if len(iv) != NONCE_SIZE or len(wrapped) != DATA_KEY_SIZE + TAG_SIZE:
                raise RoomStoreError("Unexpected output from the Keystore.")
            _write_atomic(self._datakey_path(), bytes([DATAKEY_VERSION]) + bytes(iv) + bytes(wrapped))
        self.data_key = bytearray(key)
        del key
        self._build_index()

    # ---- index and migration
    def _build_index(self):
        index, bad, old = {}, 0, []
        for fid in self._room_files():
            try:
                blob = self._read_blob(fid)
                if blob[0] == VERSION_V1:
                    old.append(fid)
                    continue
                name, _ = self._decrypt_v2(fid, blob)
            except _BadFile:
                bad += 1  # kept on disk, never deleted
                continue
            index.setdefault(name, fid)
        self.index = index
        self.notes = []
        if bad:
            self.notes.append(f"{bad} saved room file(s) could not be decrypted and were skipped.")
        self._migrate_v1(old)
        self._migrate_plaintext()

    def _save_new(self, name, room):
        fid = self.index.get(name) or secrets.token_hex(8)
        self._encrypt_file(fid, name, room)
        self.index[name] = fid
        return fid

    def _migrate_v1(self, fids):
        """Re-encrypt earlier-format files with the data key, then drop the old key."""
        remaining = list(fids)
        for fid in fids:
            try:
                blob = self._read_blob(fid)
                plain = self.keystore.old_decrypt(self._aad(fid), blob[1:1 + NONCE_SIZE],
                                                  blob[1 + NONCE_SIZE:])
                name, room = self._parse(plain)
            except (LockedError, InvalidatedError):
                self.notes.append("Some saved rooms are still in the old format; "
                                  "they'll be converted after a later unlock.")
                break
            except RoomStoreError:
                self.notes.append("1 old saved room file could not be converted and was kept.")
                continue
            if name in self.index:
                continue  # already converted under another file: keep the old file
            try:
                new_fid = self._save_new(name, room)
                if self._decrypt_file(new_fid) != (name, room):  # check before deleting
                    raise _BadFile("Conversion check failed.")
                os.remove(self._path(fid))
                remaining.remove(fid)
            except (RoomStoreError, OSError):
                self.index.pop(name, None)
                self.notes.append("1 old saved room file could not be converted and was kept.")
        if not remaining:
            try:
                if self.keystore.has_old_key():
                    self.keystore.delete_old_key()
            except RoomStoreError:
                pass

    def _migrate_plaintext(self):
        """Encrypt plaintext .json rooms (new folder, then the old ./rooms), then delete them."""
        sources = [self.folder]
        if self.legacy_dir and os.path.isdir(self.legacy_dir) and \
                os.path.realpath(self.legacy_dir) != os.path.realpath(self.folder):
            sources.append(self.legacy_dir)
        for folder in sources:
            for fname in _plain_files(folder):
                name = fname[:-len(PLAIN_EXT)]
                src = os.path.join(folder, fname)
                if name in self.index:
                    continue  # already saved encrypted: leave the plaintext alone
                data = _read_plain(src)
                if data is None:
                    self.notes.append(f"Could not migrate saved room file {fname}.")
                    continue
                try:
                    fid = self._save_new(name, data)
                    if self._decrypt_file(fid) != (name, data):  # check before deleting
                        raise _BadFile("Migration check failed.")
                    os.remove(src)
                except (RoomStoreError, OSError):
                    self.index.pop(name, None)
                    self.notes.append(f"Could not migrate saved room file {fname}.")

    # ---- public
    def list_rooms(self):
        if self.data_key is None and self._nothing_saved():
            return []  # nothing to protect: no prompt
        self._require_unlocked()
        return sorted(self.index)

    def load(self, name):
        self._require_unlocked()
        fid = self.index.get(name)
        if fid is None:
            raise RoomStoreError("That saved room no longer exists.")
        try:
            saved_name, room = self._decrypt_file(fid)
        except _BadFile:
            raise RoomStoreError("Could not decrypt that saved room.")
        if saved_name != name:
            raise RoomStoreError("Could not decrypt that saved room.")
        return room

    def save(self, name, room):
        if not isinstance(name, str) or not name.strip():
            raise RoomStoreError("Room name is required.")
        self._require_unlocked()
        self._save_new(name, room)

    def delete(self, name):
        self._require_unlocked()
        fid = self.index.get(name)
        if fid is None:
            raise RoomStoreError("That saved room no longer exists.")
        try:
            os.remove(self._path(fid))
        except FileNotFoundError:
            pass
        except OSError:
            raise RoomStoreError("Could not delete that saved room.")
        del self.index[name]

    def clear_all(self):
        """Delete every encrypted room, the wrapped data key and both Keystore keys."""
        self.lock()
        for path in [self._path(fid) for fid in self._room_files()] + [self._datakey_path()]:
            try:
                os.remove(path)
            except OSError:
                pass
        for delete in (self.keystore.delete_kek, self.keystore.delete_old_key):
            try:
                delete()
            except RoomStoreError:
                pass
        self.notes = []


# ---- Android Keystore (pyjnius)

KEK_ALIAS = "mcutiechat-rooms-kek"
OLD_KEY_ALIAS = "mcutiechat-rooms"


def _to_bytes(arr):
    """pyjnius may return byte[] as bytes, a buffer, or a list of signed ints."""
    if isinstance(arr, (bytes, bytearray)):
        return bytes(arr)
    try:
        return memoryview(arr).tobytes()
    except TypeError:
        return bytes(b & 0xFF for b in arr)


class AndroidKeystore:
    """pyjnius gives a JavaClass argument that isn't an exact type match the same score
    for every overload of that arity, and a wrong pick aborts the app in JNI. So every
    object passed to an overloaded method is cast() to the declared parameter type."""

    def __init__(self):
        from jnius import autoclass, cast, JavaException
        self._cast = cast
        self._JavaException = JavaException
        self._KeyStore = autoclass("java.security.KeyStore")
        self._KeyGenerator = autoclass("javax.crypto.KeyGenerator")
        self._Builder = autoclass("android.security.keystore.KeyGenParameterSpec$Builder")
        self._KeyProperties = autoclass("android.security.keystore.KeyProperties")
        self._Cipher = autoclass("javax.crypto.Cipher")
        self._GCMParameterSpec = autoclass("javax.crypto.spec.GCMParameterSpec")
        self._Context = autoclass("android.content.Context")
        self._PythonActivity = autoclass("org.kivy.android.PythonActivity")

    def _map(self, e):
        """Turn a Java exception into a non-secret RoomStoreError (never its message)."""
        cls = getattr(e, "classname", "") or ""
        if cls.endswith("UserNotAuthenticatedException"):
            return LockedError()
        if cls.endswith("KeyPermanentlyInvalidatedException"):
            return InvalidatedError()
        if cls.endswith("AEADBadTagException"):
            return _BadFile("Saved rooms key failed authentication.")
        print(f"room_store: Keystore error {cls.rsplit('.', 1)[-1] or type(e).__name__}")
        return RoomStoreError("Saved rooms: Keystore error.")

    def _keystore(self):
        ks = self._KeyStore.getInstance("AndroidKeyStore")
        ks.load(None)  # load(LoadStoreParameter): the only one-argument overload
        return ks

    def _has(self, alias):
        try:
            return bool(self._keystore().containsAlias(alias))
        except self._JavaException as e:
            raise self._map(e)

    def _delete(self, alias):
        try:
            ks = self._keystore()
            if ks.containsAlias(alias):
                ks.deleteEntry(alias)
        except self._JavaException as e:
            raise self._map(e)

    def _key(self, alias):
        key = self._keystore().getKey(alias, None)
        if key is None:
            raise InvalidatedError()
        return self._cast("java.security.Key", key)

    def _new_cipher(self, mode, alias, iv=None):
        c = self._Cipher.getInstance("AES/GCM/NoPadding")
        if iv is None:
            c.init(mode, self._key(alias))  # ENCRYPT: the Keystore picks the IV
        else:
            spec = self._cast("java.security.spec.AlgorithmParameterSpec",
                              self._GCMParameterSpec(TAG_SIZE * 8, iv))
            c.init(mode, self._key(alias), spec)
        return c

    # wrapping key (per-use)
    def has_kek(self):
        return self._has(KEK_ALIAS)

    def delete_kek(self):
        self._delete(KEK_ALIAS)

    def create_kek(self):
        try:
            activity = self._PythonActivity.mActivity
            km = self._cast("android.app.KeyguardManager",
                            activity.getSystemService(self._Context.KEYGUARD_SERVICE))
            if not km.isDeviceSecure():
                raise NoScreenLockError()
            kp = self._KeyProperties
            builder = self._Builder(KEK_ALIAS, kp.PURPOSE_ENCRYPT | kp.PURPOSE_DECRYPT)
            # String... varargs: pass the strings themselves. pyjnius packs them into the
            # array; a Python list would be stored as a String[] inside it and abort the app.
            builder.setBlockModes(kp.BLOCK_MODE_GCM)
            builder.setEncryptionPaddings(kp.ENCRYPTION_PADDING_NONE)
            builder.setKeySize(256)
            builder.setUserAuthenticationRequired(True)
            # 0 = every use needs its own prompt (CryptoObject); unlocking the phone doesn't count
            builder.setUserAuthenticationParameters(
                0, kp.AUTH_BIOMETRIC_STRONG | kp.AUTH_DEVICE_CREDENTIAL)
            gen = self._KeyGenerator.getInstance(kp.KEY_ALGORITHM_AES, "AndroidKeyStore")
            gen.init(self._cast("java.security.spec.AlgorithmParameterSpec", builder.build()))
            gen.generateKey()
        except self._JavaException as e:
            if (getattr(e, "classname", "") or "").endswith("IllegalStateException"):
                raise NoScreenLockError()  # thrown when no secure lock screen is set
            raise self._map(e)

    def prepare_wrap(self):
        try:
            return self._new_cipher(self._Cipher.ENCRYPT_MODE, KEK_ALIAS)
        except self._JavaException as e:
            raise self._map(e)

    def prepare_unwrap(self, iv):
        try:
            return self._new_cipher(self._Cipher.DECRYPT_MODE, KEK_ALIAS, iv)
        except self._JavaException as e:
            raise self._map(e)

    def cipher_iv(self, cipher):
        try:
            return _to_bytes(cipher.getIV())
        except self._JavaException as e:
            raise self._map(e)

    def finish(self, cipher, aad, data):
        try:
            cipher.updateAAD(aad)
            return _to_bytes(cipher.doFinal(data))
        except self._JavaException as e:
            raise self._map(e)

    # earlier 5-minute key, kept only to convert version-1 room files
    def has_old_key(self):
        return self._has(OLD_KEY_ALIAS)

    def delete_old_key(self):
        self._delete(OLD_KEY_ALIAS)

    def old_decrypt(self, aad, nonce, ct):
        try:
            if not self._keystore().containsAlias(OLD_KEY_ALIAS):
                raise InvalidatedError()
            c = self._new_cipher(self._Cipher.DECRYPT_MODE, OLD_KEY_ALIAS, nonce)
            c.updateAAD(aad)
            return _to_bytes(c.doFinal(ct))
        except self._JavaException as e:
            raise self._map(e)


def _on_android():
    return "ANDROID_ARGUMENT" in os.environ


# ---- module-level store

_store = None


class _DisabledStore:
    """Android without a working Keystore: never fall back to plaintext there."""
    encrypted = True
    notes = []

    def _fail(self, *args):
        raise RoomStoreError("Saved rooms aren't available on this device.")

    list_rooms = load = save = delete = begin_unlock = finish_unlock = _fail

    def is_locked(self):
        return False

    def lock(self):
        pass

    def clear_all(self):
        pass


def init(base_dir, legacy_dir="rooms"):
    """Set up the rooms folder. Never touches the Keystore key, so it never prompts."""
    global _store
    folder = os.path.join(base_dir, "rooms")
    os.makedirs(folder, exist_ok=True)
    if _on_android():
        try:
            if AESGCM is None:
                raise ImportError("cryptography")
            keystore = AndroidKeystore()
        except Exception as e:  # pyjnius or cryptography missing: say so, don't crash
            print(f"room_store: Keystore unavailable ({type(e).__name__}); saved rooms disabled")
            _store = _DisabledStore()
            return _store
        _store = EncryptedStore(folder, keystore, legacy_dir)
        return _store
    _store = PlainStore(folder, legacy_dir)
    return _store


def encrypted():
    return bool(_store and _store.encrypted)


def notes():
    """Non-secret messages from the last unlock/migration (skipped files etc.)."""
    return list(_store.notes) if _store else []


def is_locked():
    return bool(_store and _store.is_locked())


def lock():
    """Forget the data key (app paused or closing). Safe to call any time."""
    if _store:
        _store.lock()


def begin_unlock():
    return _store.begin_unlock()


def finish_unlock(cipher):
    _store.finish_unlock(cipher)


def list_rooms():
    return _store.list_rooms()


def load(name):
    return _store.load(name)


def save(name, data):
    _store.save(name, data)


def delete(name):
    _store.delete(name)


def clear_all():
    _store.clear_all()


# ---- self-test: python3 room_store.py (needs `cryptography`)

def _self_test():
    import shutil
    import tempfile

    class FakeCipher:
        def __init__(self, ks, mode, iv):
            self.ks, self.mode, self.iv = ks, mode, iv or os.urandom(NONCE_SIZE)
            self.authed = False

    class FakeKeystore:
        """Per-use wrapping key: a cipher only works after its own prompt (authed=True)."""
        def __init__(self):
            self.kek = None
            self.old_key = None
            self.secure = True
            self.invalidated = False
            self.old_locked = False

        def has_kek(self):
            return self.kek is not None

        def create_kek(self):
            if not self.secure:
                raise NoScreenLockError()
            self.kek = AESGCM.generate_key(256)

        def delete_kek(self):
            self.kek = None

        def _prepare(self, mode, iv):
            if self.invalidated:
                raise InvalidatedError()
            if self.kek is None:
                raise InvalidatedError()
            return FakeCipher(self, mode, iv)

        def prepare_wrap(self):
            return self._prepare("enc", None)

        def prepare_unwrap(self, iv):
            return self._prepare("dec", iv)

        def cipher_iv(self, c):
            return c.iv

        def finish(self, c, aad, data):
            if not c.authed:
                raise LockedError()
            c.authed = False  # one use per prompt
            try:
                if c.mode == "enc":
                    return AESGCM(self.kek).encrypt(c.iv, data, aad)
                return AESGCM(self.kek).decrypt(c.iv, data, aad)
            except InvalidTag:
                raise _BadFile("tag")

        def has_old_key(self):
            return self.old_key is not None

        def delete_old_key(self):
            self.old_key = None

        def old_decrypt(self, aad, nonce, ct):
            if self.old_locked:
                raise LockedError()
            if self.old_key is None:
                raise InvalidatedError()
            try:
                return AESGCM(self.old_key).decrypt(nonce, ct, aad)
            except InvalidTag:
                raise _BadFile("tag")

    def unlock(store, ok=True):
        c = store.begin_unlock()
        c.authed = ok  # the prompt
        store.finish_unlock(c)

    def expect(exc, fn, *a):
        try:
            fn(*a)
        except exc:
            return
        raise AssertionError(f"expected {exc.__name__}")

    def no_tmp(folder):
        assert not [f for f in os.listdir(folder) if f.endswith(TMP_EXT)], "temp file left behind"

    def write_v1(folder, ks, name, room):
        """A room file in the earlier format (old 5-minute Keystore key)."""
        fid = secrets.token_hex(8)
        nonce = os.urandom(NONCE_SIZE)
        plain = json.dumps({"name": name, "room": room}).encode()
        ct = AESGCM(ks.old_key).encrypt(nonce, plain, AAD_PREFIX + fid.encode())
        with open(os.path.join(folder, fid + ROOM_EXT), "wb") as f:
            f.write(bytes([VERSION_V1]) + nonce + ct)
        return fid

    room = {"username": "me", "server": "h", "port": 1883, "room": "general",
            "key": "SECRETKEY", "mqtt_username": "u", "mqtt_password": "SECRETPASS",
            "tls": False, "ca": ""}
    tmp = tempfile.mkdtemp()
    try:
        # ---- plaintext backend + old-folder migration (desktop)
        legacy = os.path.join(tmp, "legacy")
        os.makedirs(legacy)
        for n in ("old", "dup"):
            with open(os.path.join(legacy, n + ".json"), "w") as f:
                json.dump(room, f)
        folder = os.path.join(tmp, "plain")
        os.makedirs(folder)
        with open(os.path.join(folder, "dup.json"), "w") as f:
            json.dump({"room": "dup", "keep": True}, f)
        s = PlainStore(folder, legacy)
        assert s.list_rooms() == ["dup", "old"], s.list_rooms()
        assert not os.path.exists(os.path.join(legacy, "old.json")), "old file moved"
        assert os.path.exists(os.path.join(legacy, "dup.json")), "existing name: old file kept"
        assert s.load("dup") == {"room": "dup", "keep": True}, "existing room not overwritten"
        s.save("general", room)
        assert s.load("general") == room and not s.is_locked()
        s.delete("general")
        assert "general" not in s.list_rooms()
        for bad in ("../x", "a/b", "a\\b", "", ".", ".."):
            expect(RoomStoreError, s.save, bad, room)
        no_tmp(folder)

        # ---- encrypted: empty store lists without a prompt; first save needs one
        folder = os.path.join(tmp, "enc")
        os.makedirs(folder)
        ks = FakeKeystore()
        s = EncryptedStore(folder, ks)
        assert s.list_rooms() == [] and s.is_locked() and not ks.has_kek()
        expect(LockedError, s.save, "x", room)
        ks.secure = False
        expect(NoScreenLockError, s.begin_unlock)
        ks.secure = True
        c = s.begin_unlock()
        expect(LockedError, s.finish_unlock, c)  # prompt cancelled: cipher never authed
        assert s.is_locked() and not os.path.exists(os.path.join(folder, DATAKEY_FILE))
        unlock(s)
        assert not s.is_locked() and os.path.exists(os.path.join(folder, DATAKEY_FILE))
        s.save("general", room)
        s.save("../x", room)  # names are never paths here
        assert s.load("general") == room and s.list_rooms() == ["../x", "general"]
        for fname in os.listdir(folder):
            with open(os.path.join(folder, fname), "rb") as f:
                blob = f.read()
            if fname.endswith(ROOM_EXT):
                assert blob[0] == VERSION and len(fname) == 16 + len(ROOM_EXT)
            for secret in (b"SECRETKEY", b"SECRETPASS", b"general"):
                assert secret not in blob, "plaintext leaked into a file"
        no_tmp(folder)

        # lock() forgets the key; the next session needs a new prompt
        key_ref = s.data_key
        s.lock()
        assert s.is_locked() and not any(key_ref), "data key zeroed"
        expect(LockedError, s.list_rooms)
        expect(LockedError, s.load, "general")
        unlock(s)
        assert s.load("general") == room

        # a fresh store (app restart) unwraps the same data key
        s2 = EncryptedStore(folder, ks)
        expect(LockedError, s2.list_rooms)
        unlock(s2)
        assert s2.list_rooms() == ["../x", "general"]

        # renamed (swapped) file fails AAD: skipped with a note, kept on disk
        fid = s2.index["general"]
        os.rename(s2._path(fid), s2._path("0" * 16))
        s3 = EncryptedStore(folder, ks)
        unlock(s3)
        assert "general" not in s3.list_rooms() and s3.notes
        assert os.path.exists(s3._path("0" * 16)), "bad file kept"
        os.rename(s3._path("0" * 16), s3._path(fid))

        # damaged datakey.bin is refused and kept
        dk = os.path.join(folder, DATAKEY_FILE)
        with open(dk, "rb") as f:
            good = f.read()
        with open(dk, "wb") as f:
            f.write(good[:-1] + bytes([good[-1] ^ 1]))
        s4 = EncryptedStore(folder, ks)
        c = s4.begin_unlock()
        c.authed = True
        expect(_BadFile, s4.finish_unlock, c)
        assert s4.is_locked() and os.path.exists(dk)
        with open(dk, "wb") as f:
            f.write(b"\x09" + good[1:])
        expect(RoomStoreError, EncryptedStore(folder, ks).begin_unlock)
        with open(dk, "wb") as f:
            f.write(good)

        # invalidated wrapping key / key gone; clear_all removes everything
        ks.invalidated = True
        expect(InvalidatedError, EncryptedStore(folder, ks).begin_unlock)
        ks.invalidated = False
        saved_kek, ks.kek = ks.kek, None
        expect(InvalidatedError, EncryptedStore(folder, ks).begin_unlock)
        ks.kek = saved_kek
        s5 = EncryptedStore(folder, ks)
        s5.clear_all()
        assert not os.listdir(folder) and not ks.has_kek() and s5.list_rooms() == []
        # data-key files with no datakey.bin can never be opened
        s6 = EncryptedStore(folder, ks)
        unlock(s6)
        s6.save("a", room)
        os.remove(dk)
        expect(InvalidatedError, EncryptedStore(folder, ks).begin_unlock)
        EncryptedStore(folder, ks).clear_all()

        # ---- migration: v1 files (old key) + plaintext (new folder and old ./rooms)
        folder = os.path.join(tmp, "mig")
        legacy = os.path.join(tmp, "legacy2")
        os.makedirs(folder)
        os.makedirs(legacy)
        ks = FakeKeystore()
        ks.old_key = AESGCM.generate_key(256)
        v1a = write_v1(folder, ks, "test1", room)
        write_v1(folder, ks, "test2", dict(room, room="test2"))
        with open(os.path.join(folder, "migrated.json"), "w") as f:
            json.dump(room, f)
        with open(os.path.join(legacy, "fromold.json"), "w") as f:
            json.dump(room, f)
        s = EncryptedStore(folder, ks, legacy)
        expect(LockedError, s.list_rooms)

        ks.old_locked = True  # old key refuses: v1 files kept, the rest migrates
        unlock(s)
        assert s.list_rooms() == ["fromold", "migrated"], s.list_rooms()
        assert os.path.exists(s._path(v1a)) and ks.has_old_key() and s.notes
        s.lock()
        ks.old_locked = False
        unlock(s)
        assert s.list_rooms() == ["fromold", "migrated", "test1", "test2"], s.list_rooms()
        assert s.load("test2")["room"] == "test2"
        assert not os.path.exists(s._path(v1a)) and not ks.has_old_key(), "v1 file and old key gone"
        assert not _plain_files(folder) and not _plain_files(legacy), "plaintext deleted"
        for fid in s._room_files():
            assert s._read_version(fid) == VERSION
        no_tmp(folder)
    finally:
        shutil.rmtree(tmp)
    print("room_store self-tests passed")


if __name__ == "__main__":
    _self_test()
