"""QR payloads for in-person key/room exchange (see PROTOCOL.md, "QR exchange").

Two compact-JSON payload types, never containing the chat username:
  key  (b): {"type":"mqttchat-key","version":1,"room","key"}
  room (a): {"type":"mqttchat-room","version":1,"host","port","tls",
             "mqtt_user","mqtt_pass","room","key"}
"""
import json

TYPE_KEY = "mqttchat-key"
TYPE_ROOM = "mqttchat-room"
VERSION = 1

# field name -> required Python type (bool is checked separately: it's an int subclass)
_FIELDS = {
    TYPE_KEY: {"room": str, "key": str},
    TYPE_ROOM: {"host": str, "port": int, "tls": bool, "mqtt_user": str,
                "mqtt_pass": str, "room": str, "key": str},
}


def _dump(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def build_key(room, key):
    return _dump({"type": TYPE_KEY, "version": VERSION, "room": room, "key": key})


def build_room(host, port, room, key, mqtt_user="", mqtt_pass="", tls=False):
    return _dump({"type": TYPE_ROOM, "version": VERSION, "host": host, "port": port,
                  "tls": tls, "mqtt_user": mqtt_user, "mqtt_pass": mqtt_pass,
                  "room": room, "key": key})


def parse(text):
    """Parse and validate a scanned payload; returns a dict or raises ValueError."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Not a MQTT Chat QR code.")
    if not isinstance(data, dict):
        raise ValueError("Not a MQTT Chat QR code.")
    kind = data.get("type")
    if kind not in _FIELDS:
        raise ValueError(f"Unknown QR type: {kind!r}" if isinstance(kind, str) and kind
                         else "Not a MQTT Chat QR code.")
    version = data.get("version")
    if version != VERSION or isinstance(version, bool):
        raise ValueError(f"Unsupported QR version: {version!r} (this app reads version {VERSION}).")
    for name, typ in _FIELDS[kind].items():
        value = data.get(name)
        if typ is bool:
            ok = isinstance(value, bool)
        else:
            ok = isinstance(value, typ) and not isinstance(value, bool)
        if not ok:
            raise ValueError(f"QR code is missing or has an invalid '{name}'.")
    if not data["room"].strip() or not data["key"].strip():
        raise ValueError("QR code has an empty room or key.")
    if kind == TYPE_ROOM:
        if not data["host"].strip():
            raise ValueError("QR code has an empty server address.")
        if not 1 <= data["port"] <= 65535:
            raise ValueError(f"QR code has an invalid port: {data['port']}.")
        if data["tls"]:
            raise ValueError("This QR needs TLS, which this app version doesn't support yet.")
    return {name: data[name] for name in ("type", "version", *_FIELDS[kind])}


if __name__ == "__main__":
    k = build_key("chatty", "test_key")
    assert parse(k) == {"type": TYPE_KEY, "version": 1, "room": "chatty", "key": "test_key"}
    r = build_room("broker.example", 23022, "chatty", "k", "u", "p#!")
    assert parse(r)["mqtt_pass"] == "p#!" and parse(r)["tls"] is False
    for payload in (k, r):
        assert "username" not in json.loads(payload) and "user" not in json.loads(payload)
    assert parse(build_room("h", 1883, "r", "k"))["mqtt_user"] == ""

    def rejects(text, needle):
        try:
            parse(text)
        except ValueError as e:
            assert needle in str(e), (needle, str(e))
            return
        raise AssertionError(f"accepted: {text}")

    rejects("https://example.com", "Not a MQTT Chat")
    rejects("[1, 2]", "Not a MQTT Chat")
    rejects('{"type":"wifi"}', "Unknown QR type")
    rejects('{"version":1}', "Not a MQTT Chat")
    rejects(k.replace('"version":1', '"version":2'), "Unsupported QR version")
    rejects(k.replace('"version":1', '"version":true'), "Unsupported QR version")
    rejects(k.replace('"key":"test_key"', '"key":""'), "empty room or key")
    rejects(k.replace('"room":"chatty",', ''), "'room'")
    rejects(r.replace('"port":23022', '"port":"23022"'), "'port'")
    rejects(r.replace('"port":23022', '"port":70000'), "invalid port")
    rejects(r.replace('"tls":false', '"tls":0'), "'tls'")
    rejects(r.replace('"tls":false', '"tls":true'), "TLS")
    rejects(r.replace('"host":"broker.example"', '"host":" "'), "server address")
    print("example key payload: ", k)
    print("example room payload:", r)
    print("all self-tests passed")
