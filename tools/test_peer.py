"""Headless Mcutie Chat peer for testing the app against a real broker.

Joins a room with the same topics, presence and encryption as the app
(chat_crypto / PROTOCOL.md), optionally sends messages, and prints everything
it receives. Lines typed on stdin are sent as chat messages.

    python tools/test_peer.py --host BROKER --room general --send "hello"

The encryption key and MQTT password can be given via the CHAT_KEY and
MQTT_PASSWORD environment variables instead of the command line.
"""
import argparse
import json
import os
import sys
import threading
import time

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import chat_crypto  # noqa: E402
import tls_config  # noqa: E402


def log(text):
    print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--room", required=True)
    ap.add_argument("--key", default=os.environ.get("CHAT_KEY"), help="encryption key or passphrase (or CHAT_KEY)")
    ap.add_argument("--user", default="test-peer", help="chat display name")
    ap.add_argument("--mqtt-user")
    ap.add_argument("--mqtt-password", default=os.environ.get("MQTT_PASSWORD"))
    ap.add_argument("--send", action="append", default=[], help="message to send after joining (repeatable)")
    ap.add_argument("--tls", action="store_true", help="connect with TLS (verified; see --ca)")
    ap.add_argument("--ca", help="broker CA certificate file (PEM) to pin; default: public CAs (certifi)")
    ap.add_argument("--duration", type=float, default=0, help="exit after N seconds (0 = run until Ctrl-C / EOF)")
    args = ap.parse_args()

    if not args.key:
        ap.error("--key or CHAT_KEY is required")

    room = args.room.strip()
    messages_topic = f"chat/{room}/messages"
    presence_topic = f"chat/{room}/presence"
    my_presence = f"{presence_topic}/{args.user}"
    key_input = args.key.strip()
    key = chat_crypto.key_from_input(key_input, room)
    kind = "raw 256-bit key" if chat_crypto.parse_raw_key(key_input) else "scrypt passphrase"
    log(f"key mode: {kind}")

    def presence(status):
        return json.dumps({"user": args.user, "status": status, "timestamp": time.time()})

    def send(text):
        body = json.dumps({"user": args.user, "message": text, "timestamp": time.time()})
        client.publish(messages_topic, chat_crypto.encrypt(key, body.encode(), messages_topic))
        log(f"SENT  {args.user}: {text}")

    joined = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log(f"connect failed: {reason_code}")
            return
        log(f"connected to {args.host}:{args.port}{' (TLS)' if args.tls else ''}, room '{room}' as '{args.user}'")
        client.subscribe(messages_topic)
        client.subscribe(f"{presence_topic}/+")
        client.publish(my_presence, presence("online"), retain=True)
        joined.set()

    def on_message(client, userdata, msg):
        payload = msg.payload.decode(errors="replace")
        if msg.topic == messages_topic:
            try:
                data = json.loads(chat_crypto.decrypt(key, payload, messages_topic))
            except Exception as e:
                log(f"DECRYPT FAILED ({type(e).__name__}: {e}) payload={payload[:60]}...")
                return
            if data.get("user") != args.user:
                log(f"RECV  {data.get('user')}: {data.get('message')}")
        elif msg.topic.startswith(presence_topic + "/"):
            who = msg.topic.rsplit("/", 1)[-1]
            status = json.loads(payload).get("status") if payload.strip() else "cleared"
            if who != args.user:
                log(f"PRESENCE {who}: {status}")

    def on_disconnect(client, userdata, flags, reason_code, properties):
        log(f"disconnected: {reason_code}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    if args.mqtt_user:
        client.username_pw_set(args.mqtt_user, args.mqtt_password or "")
    client.will_set(my_presence, presence("offline"), retain=True)
    if args.tls:
        ca_pem = open(args.ca).read() if args.ca else None
        client.tls_set_context(tls_config.make_ssl_context(ca_pem))
    elif args.ca:
        ap.error("--ca requires --tls")
    client.connect(args.host, args.port, 60)
    client.loop_start()

    try:
        if not joined.wait(15):
            log("timed out waiting for connection")
            return 1
        for text in args.send:
            send(text)
        deadline = time.time() + args.duration if args.duration else None
        if deadline is None and sys.stdin.isatty():
            for line in sys.stdin:
                if line.strip():
                    send(line.strip())
        else:
            while deadline is None or time.time() < deadline:
                time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(my_presence, presence("offline"), retain=True).wait_for_publish(2)
        client.publish(my_presence, "", retain=True).wait_for_publish(2)
        client.loop_stop()
        client.disconnect()
        log("left room")
    return 0


if __name__ == "__main__":
    sys.exit(main())
