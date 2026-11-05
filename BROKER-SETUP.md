# Running your own Mcutie Chat broker

`install.sh` sets up a [mosquitto](https://mosquitto.org/) MQTT broker for Mcutie Chat on a fresh **Ubuntu** server (a VPS, droplet or VM):
- password logins only, with anonymous access off;
- optional TLS (Let's Encrypt or your own self-signed CA);
- a firewall (ufw).

```sh
git clone https://github.com/shaybee22/mcutie-chat && cd mcutie-chat && sudo ./install.sh
```

It asks a few questions, each with a default (press Enter to accept), configures everything, tests the broker, and prints the settings to enter in the app.

> The broker works for both the Android app and the desktop client; both speak protocol v1 and can share a room.

## What it asks

| Question | Default | Notes |
|---|---|---|
| Broker address | This server's IP (from its default route) | The domain name or IP that clients connect to. A private or LAN IP gets a warning that only that network can reach it. |
| TLS mode | `letsencrypt` for a domain, `selfsigned` for an IP | `letsencrypt` needs a domain pointing at this server. `selfsigned` creates your own CA and works with IPs. `none` sends the MQTT password in clear text. |
| Port | 8883 with TLS, 1883 without | |
| Also allow by IP? | No | Self-signed with a domain only: adds the server's IP to the certificate too. |
| Email | none | Let's Encrypt only. Used for expiry notices. |
| MQTT username / password | none | Hidden input, asked twice. On a re-run you can keep the existing password. |
| Allow SSH from | `any` | Restrict SSH to an IP or CIDR. The installer refuses a restriction that would lock out your current SSH session. |

Every question can also be answered with a flag (`--host`, `--tls`, `--port`, `--user`, `--email`, `--ssh-from`; the password comes from `$MQTT_PASSWORD`). Add `--yes` to accept defaults for the rest. Run `./install.sh --help` for the full list.

## What it changes

| Path | What |
|---|---|
| Packages | `mosquitto`, `mosquitto-clients`, `ufw`, `openssl`, `python3` (+ `certbot` for Let's Encrypt), only if missing |
| `/etc/mosquitto/conf.d/mcutie-chat.conf` | The listener: anonymous access off, password file, TLS settings. Rewritten on every run. |
| `/etc/mosquitto/passwd` | MQTT users (hashed passwords), mode 600, owned by `mosquitto` |
| `/etc/mosquitto/certs/mcutie-*.pem/.key` | The broker certificate and key (key readable by group `mosquitto` only), plus the CA or chain |
| `/etc/mosquitto/ca/` | Self-signed only: `ca.pem` and `ca.key` (root only, 700/600) |
| `/etc/mosquitto/mcutie-chat.env` | Your answers, reused as defaults on the next run |
| `/etc/letsencrypt/renewal-hooks/deploy/mcutie-chat-mosquitto.sh` | Let's Encrypt only: copies renewed certificates for mosquitto and restarts it |
| ufw | Allows SSH (any, or your IP/CIDR), allows the broker port, and enables the firewall |

After configuring, it runs a **self-test**:
- a temporary user publishes and subscribes through the real address, port and TLS mode, then is removed;
- an anonymous client must be refused.

If anything fails, it stops with an explanation, and you can fix the cause and run it again.

## Entering the broker in the app

The installer prints these at the end:
- **Server Address** and **Port**;
- **Use TLS**: on for `letsencrypt` and `selfsigned`;
- **MQTT Username** and password;
- **Broker CA certificate**:
  - *self-signed*: paste the `-----BEGIN CERTIFICATE-----` block the installer prints (on desktop you can also load it from a file);
  - *Let's Encrypt*: leave it empty, because the certificate is publicly trusted.

Once one device is set up, share the room with others in person using **Room QR**. It carries the broker settings and the CA, so they don't need to paste anything. With a self-signed CA the app trusts **only that CA** for the room (see [AndroidApp/PROTOCOL.md](AndroidApp/PROTOCOL.md), "TLS trust rules").

## Adding users

```sh
sudo ./install.sh --add-user            # asks for the name and password
sudo ./install.sh --add-user alice      # name given; password asked (or $MQTT_PASSWORD)
```

This adds the user, or sets a new password for an existing one, reloads mosquitto (connected clients stay connected) and checks that the new login works. Every user can use every room: rooms are protected by their encryption keys, not by broker permissions.

## Re-running

Re-running `sudo ./install.sh` is safe and is how you change settings. The previous answers are the defaults, so pressing Enter through everything changes nothing.
- **Self-signed:** the CA is **kept**, so apps keep trusting the broker. The broker certificate is only reissued if the address changed, it isn't signed by the current CA, or it expires within 30 days.
- **Port changes:** the old ufw rule is removed.
- **SSH restriction changes:** the old SSH rule is replaced.
- **`--new-ca`** replaces the self-signed CA on purpose. The old one is kept as `ca.pem.replaced-<date>`. Everyone then has to re-paste the new CA or re-scan a new Room QR.

## The self-signed CA private key

With a self-signed CA, `ca.key` lives on the server, where anyone who steals it could impersonate your broker to every app that trusts the CA. At the end of a self-signed install the installer offers to **print the key for an offline backup (password manager, USB stick) and then delete it from the server** (`shred`).

The key is only needed to issue a new broker certificate:
- when the broker's address changes, or
- when the broker certificate expires; the installer issues it for about 10 years so this doesn't come up.

If that's needed after you've deleted the key, either put your backup back at `/etc/mosquitto/ca/ca.key` (mode 600) and re-run, or re-run with `--new-ca`, which means everyone re-pastes or re-scans.

## Let's Encrypt notes

- The domain's A record must point at this server, and **port 80** must be reachable from the internet. That includes any cloud firewall, such as a DigitalOcean Cloud Firewall, which is separate from ufw.
- Certbot runs in standalone mode. Port 80 is opened in ufw **only while certbot runs**, by its pre and post hooks, including during automatic renewals.
- On renewal, the deploy hook copies the new certificate into `/etc/mosquitto/certs/` and restarts mosquitto. Clients reconnect automatically.
- **Status: untested.** The Let's Encrypt path hasn't been run end to end yet (see "Test status" below). Please report problems.

## Troubleshooting

- **The app can't connect over TLS ("certificate verify failed")**
  - The address in the app must match the certificate. For self-signed, that's the address you gave the installer (`openssl x509 -in /etc/mosquitto/certs/mcutie-server.pem -noout -ext subjectAltName`).
  - The pasted CA must be this broker's CA.
- **"Hostname mismatch"**
  - You're connecting by an address the certificate doesn't list. Re-run the installer with that address. For a domain plus its IP, answer yes to "Also allow clients to connect by IP".
- **Can't connect at all**
  - Check `sudo ufw status`, any cloud or router firewall, and `sudo systemctl status mosquitto`.
  - Logs: `sudo journalctl -u mosquitto` and `/var/log/mosquitto/mosquitto.log`.
- **TLS fails right after restoring a VM snapshot, or "certificate is not yet valid"**
  - Certificates are dated by the server's clock. Check it with `date -u`.
  - A restored snapshot can leave the clock far off, and chrony may refuse to correct a large jump on its own. `sudo systemctl restart chrony` fixes it.
- **Other mosquitto config files** in `/etc/mosquitto/conf.d/` that also set listeners or authentication can conflict. The installer warns about them.

## Test status

| Mode | Status |
|---|---|
Tested on a fresh **Ubuntu 26.04.1 LTS** VM (mosquitto 2.0.22), with the Android app joining over the LAN:

| Mode / feature | Status |
|---|---|
| Self-signed TLS | ✅ Tested: fresh install; the app and a test client connect with the CA pinned |
| No TLS | ✅ Tested: fresh install; the app and a test client connect; anonymous clients are refused |
| Re-run with the same answers | ✅ Tested: no changes (same CA and certificate, users, firewall, config) |
| `--add-user` | ✅ Tested: the new user works, existing users unaffected, wrong passwords refused |
| CA key backup + delete | ✅ Tested: re-runs keep working; an address change is refused with the `--new-ca` explanation |
| SSH restriction | ✅ Tested: only the given IP can reach SSH; the broker port stays open; the lockout guard refuses a range excluding your session |
| Port change on re-run | ✅ Tested: the old port is closed in ufw |
| Input errors (bad port/user/CIDR/address, LE with an IP, not root, mismatched passwords) | ✅ Tested: clear message, nothing changed |
| Let's Encrypt | **Untested** (no public domain on the test VM) |
| Other Ubuntu releases (e.g. 24.04 LTS) | Expected to work (same tools), but **untested** |
