"""Saved rooms: where they live and how they're protected (no Kivy imports).

Rooms live in <user_data_dir>/rooms. On Android that is files/rooms, next to
files/app: python-for-android deletes files/app whenever an updated APK first
starts, so rooms kept there (the old ./rooms) were lost on every update.

Android: each room is one file <16 random hex>.room holding
    0x01 || 12-byte nonce || AES-256-GCM(ciphertext + 16-byte tag)
over the JSON {"name": <room name>, "room": {...saved fields...}}, with
AAD "mcutiechat-room:<file id>". The key is an AES-256 key generated inside the
Android Keystore (alias mcutiechat-rooms). It can't be exported, and it needs
the user to authenticate (strong biometric or screen-lock PIN/pattern/password)
within the last 5 minutes. Room names are inside the ciphertext, so nothing is
listed until the user unlocks.

Desktop and other non-Android runs: no Keystore. The Kivy desktop build is for
development (the real desktop client is ../mqchat.py), so rooms stay plaintext
<name>.json files there, as before. Nothing ever locks.

Never put room contents, keys or passwords into exceptions, prints or logs:
error messages here are fixed strings.
"""
import json
import os
import secrets

VERSION = 1
NONCE_SIZE = 12
TAG_SIZE = 16
AAD_PREFIX = b"mcutiechat-room:"
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
    """One .room file failed to decrypt or parse (damaged, renamed or swapped)."""


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
    """Android: AES-256-GCM files, key held by the Keystore (see module docstring).

    cipher must provide has_key(), create_key(), delete_key(),
    encrypt(aad, plaintext) -> (nonce, ciphertext_and_tag) and
    decrypt(aad, nonce, ciphertext_and_tag) -> plaintext, raising
    LockedError / InvalidatedError / NoScreenLockError / _BadFile.
    """
    encrypted = True

    def __init__(self, folder, cipher, legacy_dir=None):
        self.folder = folder
        self.cipher = cipher
        self.legacy_dir = legacy_dir
        self.index = None  # name -> file id, built by the first unlocked list_rooms()
        self.notes = []

    # ---- files
    def _room_files(self):
        try:
            return sorted(f[:-len(ROOM_EXT)] for f in os.listdir(self.folder) if f.endswith(ROOM_EXT))
        except OSError:
            return []

    def _path(self, fid):
        return os.path.join(self.folder, fid + ROOM_EXT)

    def _decrypt_file(self, fid):
        try:
            with open(self._path(fid), "rb") as f:
                blob = f.read()
        except OSError:
            raise _BadFile("Could not read a saved room file.")
        if len(blob) < 1 + NONCE_SIZE + TAG_SIZE or blob[0] != VERSION:
            raise _BadFile("Unknown saved room file format.")
        plain = self.cipher.decrypt(AAD_PREFIX + fid.encode("ascii"),
                                    blob[1:1 + NONCE_SIZE], blob[1 + NONCE_SIZE:])
        try:
            obj = json.loads(plain.decode("utf-8"))
            name, room = obj["name"], obj["room"]
            if not isinstance(name, str) or not isinstance(room, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise _BadFile("Damaged saved room file.")
        return name, room

    def _encrypt_file(self, fid, name, room):
        plain = json.dumps({"name": name, "room": room}).encode("utf-8")
        nonce, ct = self.cipher.encrypt(AAD_PREFIX + fid.encode("ascii"), plain)
        if len(nonce) != NONCE_SIZE:
            raise RoomStoreError("Unexpected nonce size from the Keystore.")
        _write_atomic(self._path(fid), bytes([VERSION]) + bytes(nonce) + bytes(ct))

    def _ensure_key(self):
        if not self.cipher.has_key():
            self.cipher.create_key()

    # ---- index and migration
    def _ensure_index(self):
        if self.index is not None:
            return
        fids = self._room_files()
        if fids and not self.cipher.has_key():
            raise InvalidatedError()  # files with no key: nothing can ever open them
        index, bad = {}, 0
        for fid in fids:
            try:
                name, _ = self._decrypt_file(fid)
            except _BadFile:
                bad += 1  # kept on disk, never deleted
                continue
            index.setdefault(name, fid)
        self.index = index
        self.notes = []
        if bad:
            self.notes.append(f"{bad} saved room file(s) could not be decrypted and were skipped.")
        try:
            self._migrate_plaintext()
        except RoomStoreError:
            self.index = None  # locked or no key mid-migration: rebuild on the next try
            raise

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
                    self._save_new(name, data)
                    fid = self.index[name]
                    if self._decrypt_file(fid) != (name, data):  # check before deleting
                        raise _BadFile("Migration check failed.")
                    os.remove(src)
                except (LockedError, InvalidatedError, NoScreenLockError):
                    raise
                except (RoomStoreError, OSError):
                    self.index.pop(name, None)
                    self.notes.append(f"Could not migrate saved room file {fname}.")

    def _save_new(self, name, room):
        self._ensure_key()
        fid = self.index.get(name) or secrets.token_hex(8)
        self._encrypt_file(fid, name, room)
        self.index[name] = fid

    # ---- public
    def list_rooms(self):
        self._ensure_index()
        return sorted(self.index)

    def load(self, name):
        self._ensure_index()
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
        self._ensure_index()  # first: files without a key must report InvalidatedError
        self._save_new(name, room)

    def delete(self, name):
        self._ensure_index()
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
        """Delete every encrypted room and the Keystore key (after invalidation)."""
        for fid in self._room_files():
            try:
                os.remove(self._path(fid))
            except OSError:
                pass
        try:
            self.cipher.delete_key()
        except RoomStoreError:
            pass
        self.index = {}
        self.notes = []


# ---- Android Keystore cipher (pyjnius)

KEY_ALIAS = "mcutiechat-rooms"
AUTH_SECONDS = 300


def _to_bytes(arr):
    """pyjnius may return byte[] as bytes, a buffer, or a list of signed ints."""
    if isinstance(arr, (bytes, bytearray)):
        return bytes(arr)
    try:
        return memoryview(arr).tobytes()
    except TypeError:
        return bytes(b & 0xFF for b in arr)


class KeystoreCipher:
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
        self._SDK_INT = autoclass("android.os.Build$VERSION").SDK_INT
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
            return _BadFile("Saved room file failed authentication.")
        print(f"room_store: Keystore error {cls.rsplit('.', 1)[-1] or type(e).__name__}")
        return RoomStoreError("Saved rooms: Keystore error.")

    def _keystore(self):
        ks = self._KeyStore.getInstance("AndroidKeyStore")
        ks.load(None)
        return ks

    def _key(self):
        key = self._keystore().getKey(KEY_ALIAS, None)
        if key is None:
            raise InvalidatedError()
        return key

    def has_key(self):
        try:
            return bool(self._keystore().containsAlias(KEY_ALIAS))
        except self._JavaException as e:
            raise self._map(e)

    def create_key(self):
        try:
            activity = self._PythonActivity.mActivity
            km = self._cast("android.app.KeyguardManager",
                            activity.getSystemService(self._Context.KEYGUARD_SERVICE))
            if not km.isDeviceSecure():
                raise NoScreenLockError()
            kp = self._KeyProperties
            builder = self._Builder(KEY_ALIAS, kp.PURPOSE_ENCRYPT | kp.PURPOSE_DECRYPT)
            builder.setBlockModes([kp.BLOCK_MODE_GCM])
            builder.setEncryptionPaddings([kp.ENCRYPTION_PADDING_NONE])
            builder.setKeySize(256)
            builder.setUserAuthenticationRequired(True)
            if self._SDK_INT >= 30:
                builder.setUserAuthenticationParameters(
                    AUTH_SECONDS, kp.AUTH_BIOMETRIC_STRONG | kp.AUTH_DEVICE_CREDENTIAL)
            else:
                builder.setUserAuthenticationValidityDurationSeconds(AUTH_SECONDS)
            gen = self._KeyGenerator.getInstance(kp.KEY_ALGORITHM_AES, "AndroidKeyStore")
            gen.init(builder.build())
            gen.generateKey()
        except self._JavaException as e:
            if (getattr(e, "classname", "") or "").endswith("IllegalStateException"):
                raise NoScreenLockError()  # thrown when no secure lock screen is set
            raise self._map(e)

    def delete_key(self):
        try:
            ks = self._keystore()
            if ks.containsAlias(KEY_ALIAS):
                ks.deleteEntry(KEY_ALIAS)
        except self._JavaException as e:
            raise self._map(e)

    def encrypt(self, aad, plaintext):
        try:
            c = self._Cipher.getInstance("AES/GCM/NoPadding")
            c.init(self._Cipher.ENCRYPT_MODE, self._key())  # the Keystore picks the nonce
            c.updateAAD(aad)
            ct = _to_bytes(c.doFinal(plaintext))
            return _to_bytes(c.getIV()), ct
        except self._JavaException as e:
            raise self._map(e)

    def decrypt(self, aad, nonce, ct):
        try:
            c = self._Cipher.getInstance("AES/GCM/NoPadding")
            c.init(self._Cipher.DECRYPT_MODE, self._key(),
                   self._GCMParameterSpec(TAG_SIZE * 8, nonce))
            c.updateAAD(aad)
            return _to_bytes(c.doFinal(ct))
        except self._JavaException as e:
            raise self._map(e)


def _on_android():
    return "ANDROID_ARGUMENT" in os.environ


# ---- module-level store

_store = None


def init(base_dir, legacy_dir="rooms"):
    """Set up the rooms folder. Never touches the key, so it never prompts."""
    global _store
    folder = os.path.join(base_dir, "rooms")
    os.makedirs(folder, exist_ok=True)
    if _on_android():
        try:
            cipher = KeystoreCipher()
        except Exception as e:  # pyjnius missing or a class not found: say so, don't crash
            print(f"room_store: Keystore unavailable ({type(e).__name__}); saved rooms disabled")
            cipher = None
        if cipher is not None:
            _store = EncryptedStore(folder, cipher, legacy_dir)
            return _store
        _store = _DisabledStore()
        return _store
    _store = PlainStore(folder, legacy_dir)
    return _store


class _DisabledStore:
    """Android without a working Keystore: never fall back to plaintext there."""
    encrypted = True
    notes = []

    def _fail(self, *args):
        raise RoomStoreError("Saved rooms aren't available on this device.")

    list_rooms = load = save = delete = _fail

    def clear_all(self):
        pass


def encrypted():
    return bool(_store and _store.encrypted)


def notes():
    """Non-secret messages from the last list/migration (skipped files etc.)."""
    return list(_store.notes) if _store else []


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


# ---- self-test: python3 room_store.py (needs `cryptography` for the fake cipher)

def _self_test():
    import shutil
    import tempfile
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    class FakeCipher:
        def __init__(self):
            self.key = None
            self.locked = False
            self.invalidated = False
            self.secure = True

        def has_key(self):
            return self.key is not None

        def create_key(self):
            if not self.secure:
                raise NoScreenLockError()
            self.key = AESGCM.generate_key(256)

        def delete_key(self):
            self.key = None

        def _check(self):
            if self.invalidated:
                raise InvalidatedError()
            if self.locked:
                raise LockedError()
            if self.key is None:
                raise InvalidatedError()

        def encrypt(self, aad, plaintext):
            self._check()
            nonce = os.urandom(NONCE_SIZE)
            return nonce, AESGCM(self.key).encrypt(nonce, plaintext, aad)

        def decrypt(self, aad, nonce, ct):
            self._check()
            from cryptography.exceptions import InvalidTag
            try:
                return AESGCM(self.key).decrypt(nonce, ct, aad)
            except InvalidTag:
                raise _BadFile("tag")

    def expect(exc, fn, *a):
        try:
            fn(*a)
        except exc:
            return
        raise AssertionError(f"expected {exc.__name__}")

    def no_tmp(folder):
        assert not [f for f in os.listdir(folder) if f.endswith(TMP_EXT)], "temp file left behind"

    room = {"username": "me", "server": "h", "port": 1883, "room": "general",
            "key": "SECRETKEY", "mqtt_username": "u", "mqtt_password": "SECRETPASS",
            "tls": False, "ca": ""}
    tmp = tempfile.mkdtemp()
    try:
        # plaintext backend + old-folder migration
        legacy = os.path.join(tmp, "legacy")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "old.json"), "w") as f:
            json.dump(room, f)
        with open(os.path.join(legacy, "dup.json"), "w") as f:
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
        assert s.load("general") == room
        s.delete("general")
        assert "general" not in s.list_rooms()
        for bad in ("../x", "a/b", "a\\b", "", ".", ".."):
            expect(RoomStoreError, s.save, bad, room)
        no_tmp(folder)

        # encrypted backend
        folder = os.path.join(tmp, "enc")
        os.makedirs(folder)
        legacy = os.path.join(tmp, "legacy2")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "fromold.json"), "w") as f:
            json.dump(room, f)
        with open(os.path.join(folder, "plainnew.json"), "w") as f:
            json.dump(room, f)
        c = FakeCipher()
        s = EncryptedStore(folder, c, legacy)
        c.locked = True
        expect(NoScreenLockError, lambda: (setattr(c, "secure", False), s.save("x", room)))
        c.secure = True
        expect(LockedError, s.save, "x", room)  # key made, but locked
        assert c.has_key() and s.index is None
        c.locked = False
        assert s.list_rooms() == ["fromold", "plainnew"], s.list_rooms()
        assert not _plain_files(folder) and not _plain_files(legacy), "plaintext deleted after migration"
        s.save("general", room)
        s.save("../x", room)  # names are never paths here
        assert s.load("general") == room and s.load("../x") == room
        files = os.listdir(folder)
        assert all(f.endswith(ROOM_EXT) and len(f) == 16 + len(ROOM_EXT) for f in files), files
        for fname in files:
            with open(os.path.join(folder, fname), "rb") as f:
                blob = f.read()
            assert blob[0] == VERSION
            for secret in (b"SECRETKEY", b"SECRETPASS", b"general", b"fromold"):
                assert secret not in blob, "plaintext leaked into a .room file"
        assert sorted(files) == sorted(f for f in os.listdir(folder)), "no temp files"

        # a fresh store (app restart) decrypts the index again
        s2 = EncryptedStore(folder, c)
        c.locked = True
        expect(LockedError, s2.list_rooms)
        c.locked = False
        assert s2.list_rooms() == sorted(["../x", "fromold", "general", "plainnew"])

        # renamed (swapped) file fails AAD and is skipped, not deleted
        fid = s2.index["general"]
        os.rename(os.path.join(folder, fid + ROOM_EXT), os.path.join(folder, "0" * 16 + ROOM_EXT))
        s3 = EncryptedStore(folder, c)
        assert "general" not in s3.list_rooms() and s3.notes, "swapped file skipped with a note"
        assert os.path.exists(os.path.join(folder, "0" * 16 + ROOM_EXT)), "bad file kept"

        # wrong version byte is refused
        fid = s3.index["fromold"]
        p = os.path.join(folder, fid + ROOM_EXT)
        with open(p, "rb") as f:
            blob = f.read()
        with open(p, "wb") as f:
            f.write(b"\x02" + blob[1:])
        s4 = EncryptedStore(folder, c)
        assert "fromold" not in s4.list_rooms()

        # existing encrypted name wins over a plaintext file of that name
        with open(os.path.join(folder, "plainnew.json"), "w") as f:
            json.dump({"other": 1}, f)
        s5 = EncryptedStore(folder, c)
        s5.list_rooms()
        assert s5.load("plainnew") == room and os.path.exists(os.path.join(folder, "plainnew.json"))
        os.remove(os.path.join(folder, "plainnew.json"))

        # delete
        s5.delete("../x")
        assert "../x" not in s5.list_rooms()

        # invalidated key, and files with no key at all
        c.invalidated = True
        expect(InvalidatedError, EncryptedStore(folder, c).list_rooms)
        c.invalidated = False
        c.key = None
        expect(InvalidatedError, EncryptedStore(folder, c).list_rooms)
        s6 = EncryptedStore(folder, c)
        s6.clear_all()
        assert not os.listdir(folder) and not c.has_key() and s6.list_rooms() == []
        s6.save("again", room)
        assert s6.list_rooms() == ["again"]
        no_tmp(folder)
    finally:
        shutil.rmtree(tmp)
    print("room_store self-tests passed")


if __name__ == "__main__":
    _self_test()
