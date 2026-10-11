"""Message encryption for MQTT Chat (wire format v1, see PROTOCOL.md).

Payload = base64( version(1 byte) || nonce(12 bytes) || AES-256-GCM ciphertext+tag )
AAD     = the MQTT messages topic, e.g. "chat/general/messages"
Key     = a generated 256-bit base64url key used directly, otherwise
          scrypt(passphrase, salt=sha256("mqttchat-scrypt-v1:" + room))
"""
import base64
import hashlib
import os
import re

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    AVAILABLE = True
except ImportError:
    AESGCM = None
    Scrypt = None
    AVAILABLE = False

VERSION = 1
NONCE_SIZE = 12
TAG_SIZE = 16
KEY_SIZE = 32

SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_PREFIX = b"mqttchat-scrypt-v1:"

# 32 bytes in base64url is 43 characters plus one optional '=' of padding
RAW_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}=?$")


def generate_key():
    """Return a new random 256-bit key as base64url text (44 chars)."""
    return base64.urlsafe_b64encode(os.urandom(KEY_SIZE)).decode()


def parse_raw_key(text):
    """Return the 32 key bytes if text is a generated key, else None."""
    text = text.strip()
    if not RAW_KEY_RE.match(text):
        return None
    try:
        key = base64.urlsafe_b64decode(text.rstrip("=") + "=")
    except ValueError:
        return None
    return key if len(key) == KEY_SIZE else None


def room_salt(room):
    return hashlib.sha256(SALT_PREFIX + room.encode("utf-8")).digest()


def key_from_input(text, room):
    """Turn the key field into a 32-byte AES key (raw key or scrypt passphrase)."""
    key = parse_raw_key(text)
    if key is not None:
        return key
    kdf = Scrypt(salt=room_salt(room), length=KEY_SIZE, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(text.encode("utf-8"))


def _seal(key, nonce, plaintext, topic):
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, topic.encode("utf-8"))
    return base64.b64encode(bytes([VERSION]) + nonce + ciphertext).decode()


def encrypt(key, plaintext, topic):
    """Encrypt plaintext bytes for the given messages topic; returns base64 text."""
    return _seal(key, os.urandom(NONCE_SIZE), plaintext, topic)


def decrypt(key, payload, topic):
    """Decrypt a base64 payload from the given topic; returns plaintext bytes.

    Raises ValueError for a malformed payload or unknown version, and
    cryptography.exceptions.InvalidTag for a wrong key, topic, or tampering.
    """
    data = base64.b64decode(payload, validate=True)
    if len(data) < 1 + NONCE_SIZE + TAG_SIZE:
        raise ValueError("payload too short")
    if data[0] != VERSION:
        raise ValueError(f"unknown payload version {data[0]}")
    nonce = data[1:1 + NONCE_SIZE]
    return AESGCM(key).decrypt(nonce, data[1 + NONCE_SIZE:], topic.encode("utf-8"))


if __name__ == "__main__":
    from cryptography.exceptions import InvalidTag

    topic = "chat/general/messages"
    key = key_from_input(generate_key(), "general")
    msg = b'{"user": "alice", "message": "hi", "timestamp": 1.0}'

    payload = encrypt(key, msg, topic)
    assert decrypt(key, payload, topic) == msg
    assert encrypt(key, msg, topic) != payload, "nonce must differ per message"

    def rejects(p, k=key, t=topic, exc=(InvalidTag,)):
        try:
            decrypt(k, p, t)
        except exc:
            return True
        return False

    raw = bytearray(base64.b64decode(payload))
    raw[-1] ^= 1
    assert rejects(base64.b64encode(bytes(raw)).decode()), "tampering"
    assert rejects(payload, t="chat/other/messages"), "wrong topic"
    assert rejects(payload, k=os.urandom(KEY_SIZE)), "wrong key"
    raw = bytearray(base64.b64decode(payload))
    raw[0] = 2
    assert rejects(base64.b64encode(bytes(raw)).decode(), exc=(ValueError,)), "version"
    assert rejects(base64.b64encode(b"\x01short").decode(), exc=(ValueError,)), "length"

    gen = generate_key()
    assert len(gen) == 44 and parse_raw_key(gen) is not None
    assert parse_raw_key(gen.rstrip("=")) is not None
    assert key_from_input(gen, "a") == key_from_input(gen, "b"), "raw key ignores room"
    for not_raw in ["hunter2", "correct horse battery staple", "", "A" * 44, gen[:-2]]:
        assert parse_raw_key(not_raw) is None, not_raw

    k1 = key_from_input("hunter2", "general")
    assert k1 == key_from_input("hunter2", "general")
    assert k1 != key_from_input("hunter2", "General")
    assert len(k1) == KEY_SIZE

    # Fixed test vector for porting (also recorded in PROTOCOL.md)
    vec_key = bytes(range(32))
    vec_nonce = bytes(range(12))
    print("test vector key (base64url):", base64.urlsafe_b64encode(vec_key).decode())
    print("test vector nonce (hex):    ", vec_nonce.hex())
    print("test vector payload:        ", _seal(vec_key, vec_nonce, msg, topic))
    print("scrypt('hunter2', room 'general') (hex):", k1.hex())
    print("all self-tests passed")
