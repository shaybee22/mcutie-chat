#!/usr/bin/env bash
# Mcutie Chat broker installer for Ubuntu (mosquitto + TLS + ufw).
#
#   sudo ./install.sh              install, or re-run to change settings (safe to re-run)
#   sudo ./install.sh --add-user   add or update an MQTT user on an existing install
#
# See BROKER-SETUP.md for details. Run with --help for all options.
set -Eeuo pipefail
umask 022

CONF_FILE=/etc/mosquitto/conf.d/mcutie-chat.conf
PASSWD_FILE=/etc/mosquitto/passwd
STATE_FILE=/etc/mosquitto/mcutie-chat.env
CERT_DIR=/etc/mosquitto/certs
CA_DIR=/etc/mosquitto/ca
CA_KEY=$CA_DIR/ca.key
CA_PEM=$CA_DIR/ca.pem
SRV_KEY=$CERT_DIR/mcutie-server.key
SRV_PEM=$CERT_DIR/mcutie-server.pem
SRV_CA=$CERT_DIR/mcutie-ca.pem
LE_HOOK=/etc/letsencrypt/renewal-hooks/deploy/mcutie-chat-mosquitto.sh
CERT_DAYS=3650   # ~10 years: lets the CA key be taken offline without forcing re-scans later

STEP="starting"
TMP_DIR=""
SELFTEST_USER=""

# ---------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then BOLD=$'\e[1m'; RED=$'\e[31m'; YEL=$'\e[33m'; GRN=$'\e[32m'; RST=$'\e[0m'
else BOLD=""; RED=""; YEL=""; GRN=""; RST=""; fi
say()  { printf '%s\n' "$*"; }
step() { STEP="$1"; printf '\n%s==> %s%s\n' "$BOLD" "$1" "$RST"; }
ok()   { printf '%s  ok:%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%sWARNING:%s %s\n' "$YEL" "$RST" "$*" >&2; }
die() {
    trap - ERR   # an expected, explained failure: no second "unexpected failure" message
    printf '\n%sERROR:%s %s\n' "$RED" "$RST" "$1" >&2
    if [[ -n "${2:-}" ]]; then printf '  %s\n' "$2" >&2; fi
    exit 1
}

on_err() {
    printf '\n%sERROR:%s unexpected failure during "%s" (line %s, command: %s).\n' \
        "$RED" "$RST" "$STEP" "$1" "$2" >&2
    printf '  Fix the cause and re-run: the installer is safe to run again.\n' >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

cleanup() {
    trap - ERR
    # Always remove the temporary self-test login, even after a failure
    if [[ -n "$SELFTEST_USER" && -f "$PASSWD_FILE" && -d "$TMP_DIR" ]]; then
        passwd_update "$SELFTEST_USER" delete >/dev/null 2>&1 || true
        systemctl reload mosquitto >/dev/null 2>&1 || true
    fi
    if [[ -n "$TMP_DIR" ]]; then rm -rf "$TMP_DIR"; fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Usage: sudo ./install.sh [options]
       sudo ./install.sh --add-user [NAME]

Installs and configures a mosquitto MQTT broker for Mcutie Chat: no anonymous
access, password logins, optional TLS (Let's Encrypt or a self-signed CA), ufw.
Every question has a default; options below answer them up front.

Options:
  --host ADDR           Broker address clients use: domain name or IP
  --tls MODE            letsencrypt | selfsigned | none
  --port N              Listener port (default 8883 with TLS, 1883 without)
  --user NAME           MQTT username to create/update
  --email ADDR          Let's Encrypt account email (optional)
  --ssh-from CIDR|any   Restrict SSH in ufw to this source IP/CIDR ("any" = unrestricted)
  --new-ca              Self-signed: replace the CA (everyone must re-scan/re-paste)
  --add-user [NAME]     Add or update an MQTT user on an existing install
  --yes                 Accept defaults for anything not given (non-interactive)
  -h, --help            Show this help

The MQTT password is asked for (hidden, twice), or read from $MQTT_PASSWORD.
EOF
}

# ---------------------------------------------------------------- arguments
OPT_HOST="" OPT_TLS="" OPT_PORT="" OPT_USER="" OPT_EMAIL="" OPT_SSH_FROM=""
NEW_CA=0 ASSUME_YES=0 MODE=install
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)      OPT_HOST="${2:?--host needs a value}"; shift 2 ;;
        --tls)       OPT_TLS="${2:?--tls needs a value}"; shift 2 ;;
        --port)      OPT_PORT="${2:?--port needs a value}"; shift 2 ;;
        --user)      OPT_USER="${2:?--user needs a value}"; shift 2 ;;
        --email)     OPT_EMAIL="${2:?--email needs a value}"; shift 2 ;;
        --ssh-from)  OPT_SSH_FROM="${2:?--ssh-from needs a value}"; shift 2 ;;
        --new-ca)    NEW_CA=1; shift ;;
        --yes|-y)    ASSUME_YES=1; shift ;;
        --add-user)  MODE=add-user; shift
                     if [[ $# -gt 0 && "$1" != -* ]]; then OPT_USER="$1"; shift; fi ;;
        -h|--help)   usage; exit 0 ;;
        *)           die "Unknown option: $1" "Run ./install.sh --help for usage." ;;
    esac
done

# ---------------------------------------------------------------- prompt helpers
interactive() { [[ -t 0 && $ASSUME_YES -eq 0 ]]; }

# ask VAR "Question" DEFAULT [flag-name] [flag-value]
# A value given by flag answers the question without prompting; otherwise prompt (or, when not
# interactive, take the default).
ask() {
    local __var=$1 question=$2 default=$3 flag=${4:-} given=${5:-} answer
    if [[ -n "$given" ]]; then
        say "$question: $given (from $flag)"
        printf -v "$__var" '%s' "$given"
        return
    fi
    if interactive; then
        if [[ -n "$default" ]]; then read -r -p "$question [$default]: " answer
        else read -r -p "$question: " answer; fi
        answer=${answer:-$default}
    elif [[ -n "$default" ]]; then
        answer=$default
    else
        die "No answer for: $question" "Run interactively, or pass ${flag:-the matching option} (see --help)."
    fi
    printf -v "$__var" '%s' "$answer"
}

# ask_yn "Question" y|n  -> returns 0 for yes
ask_yn() {
    local question=$1 default=$2 answer hint="[y/N]"
    [[ $default == y ]] && hint="[Y/n]"
    if ! interactive; then [[ $default == y ]]; return; fi
    read -r -p "$question $hint: " answer
    answer=${answer:-$default}
    [[ ${answer,,} == y || ${answer,,} == yes ]]
}

# ask_password VAR "label"
ask_password() {
    local __var=$1 label=$2 p1 p2
    if [[ -n "${MQTT_PASSWORD:-}" ]]; then printf -v "$__var" '%s' "$MQTT_PASSWORD"; return; fi
    [[ -t 0 ]] || die "No password for $label" "Run interactively, or set MQTT_PASSWORD."
    while true; do
        read -r -s -p "Password for $label: " p1; echo
        read -r -s -p "Repeat password: " p2; echo
        if [[ -z "$p1" ]]; then warn "The password can't be empty."; continue; fi
        if [[ "$p1" != "$p2" ]]; then warn "The passwords don't match, try again."; continue; fi
        break
    done
    printf -v "$__var" '%s' "$p1"
}

# ---------------------------------------------------------------- validation
is_ip()     { python3 -c 'import ipaddress,sys; ipaddress.ip_address(sys.argv[1])' "$1" 2>/dev/null; }
is_public() { python3 -c 'import ipaddress,sys; sys.exit(0 if ipaddress.ip_address(sys.argv[1]).is_global else 1)' "$1"; }
is_cidr()   { python3 -c 'import ipaddress,sys; ipaddress.ip_network(sys.argv[1], strict=False)' "$1" 2>/dev/null; }
in_cidr()   { python3 -c 'import ipaddress,sys; sys.exit(0 if ipaddress.ip_address(sys.argv[1]) in ipaddress.ip_network(sys.argv[2], strict=False) else 1)' "$1" "$2"; }
is_domain() { [[ $1 =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]]; }
is_port()   { [[ $1 =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }
valid_user() { [[ $1 =~ ^[A-Za-z0-9._@-]{1,64}$ ]]; }

detect_ip() {
    # Source address of the default route (no external lookups). Public IP on most VPSs.
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i+1); exit }}'
}

user_exists() { [[ -f "$PASSWD_FILE" ]] && grep -q "^${1}:" "$PASSWD_FILE"; }

# passwd_update USER [delete]: add/update USER (password read from stdin), or delete USER.
# The broker needs the file owned by mosquitto (mode 600) so it can re-read it on reload after
# dropping privileges, while mosquitto_passwd run as root warns about any owner but root. Editing
# a root-owned copy and installing it back keeps both quiet and makes each change atomic.
passwd_update() {
    local user=$1 action=${2:-set} work
    work=$(mktemp "$TMP_DIR/passwd.XXXXXX")
    if [[ -f "$PASSWD_FILE" ]]; then cat "$PASSWD_FILE" > "$work"; fi
    if [[ $action == delete ]]; then mosquitto_passwd -D "$work" "$user" >/dev/null
    else mosquitto_passwd "$work" "$user" >/dev/null; fi
    install -m 600 -o mosquitto -g mosquitto "$work" "$PASSWD_FILE"
    rm -f "$work"
}

# set_password USER PASSWORD (via stdin, not argv, which other local users could see in ps)
set_password() { printf '%s\n%s\n' "$2" "$2" | passwd_update "$1"; }

# client_opts DIR USER PASSWORD -> writes mosquitto_pub/_sub option files (keeps secrets out of argv)
client_opts() {
    local dir=$1
    mkdir -p "$dir"
    printf -- '-u %s\n-P %s\n' "$2" "$3" > "$dir/mosquitto_pub"
    cp "$dir/mosquitto_pub" "$dir/mosquitto_sub"
    chmod 600 "$dir/mosquitto_pub" "$dir/mosquitto_sub"
}

tls_client_args() {
    case "$TLS_MODE" in
        selfsigned)  printf '%s\n' --cafile "$CA_PEM" ;;
        letsencrypt) printf '%s\n' --capath /etc/ssl/certs ;;
    esac
}

# roundtrip CONFIG_DIR -> 0 if a message published with these credentials comes back
roundtrip() {
    local cfg=$1 topic token out tls_args=()
    topic="mcutie-chat/selftest/$(openssl rand -hex 6)"
    token="selftest-$(openssl rand -hex 8)"
    out="$TMP_DIR/sub.out"
    mapfile -t tls_args < <(tls_client_args)
    XDG_CONFIG_HOME=$cfg mosquitto_sub -h "$HOST" -p "$PORT" "${tls_args[@]}" -t "$topic" -C 1 -W 10 \
        > "$out" 2> "$TMP_DIR/sub.err" &
    local sub_pid=$!
    sleep 1
    if ! XDG_CONFIG_HOME=$cfg mosquitto_pub -h "$HOST" -p "$PORT" "${tls_args[@]}" -t "$topic" -m "$token" \
            2> "$TMP_DIR/pub.err"; then
        wait "$sub_pid" 2>/dev/null || true
        sed 's/^/    /' "$TMP_DIR/pub.err" >&2
        return 1
    fi
    wait "$sub_pid" 2>/dev/null || true
    if [[ "$(cat "$out")" != "$token" ]]; then
        sed 's/^/    /' "$TMP_DIR/sub.err" >&2
        return 1
    fi
}

# ---------------------------------------------------------------- preflight
preflight() {
    step "Checking the system"
    [[ $EUID -eq 0 ]] || die "This installer must run as root." "Run: sudo ./install.sh"
    [[ -r /etc/os-release ]] || die "Can't read /etc/os-release, so this doesn't look like Ubuntu."
    # shellcheck disable=SC1091
    . /etc/os-release
    [[ "${ID:-}" == ubuntu ]] || die "This installer supports Ubuntu only (found: ${PRETTY_NAME:-unknown})."
    command -v systemctl >/dev/null || die "systemd is required (systemctl not found)."
    ok "$PRETTY_NAME, running as root"
    TMP_DIR=$(mktemp -d)
    chmod 700 "$TMP_DIR"
}

install_packages() {
    local missing=() pkg
    for pkg in "$@"; do
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || missing+=("$pkg")
    done
    if [[ ${#missing[@]} -eq 0 ]]; then ok "packages already installed: $*"; return; fi
    say "Installing: ${missing[*]}"
    # NEEDRESTART_SUSPEND: skip needrestart's interactive scan and progress output during apt
    DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get update -q >/dev/null \
        || die "apt-get update failed." "Check the network and /etc/apt/sources.list, then re-run."
    DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -y -q "${missing[@]}" >/dev/null \
        || die "Installing ${missing[*]} failed." "Run 'apt-get install ${missing[*]}' to see why, then re-run."
    ok "installed: ${missing[*]}"
}

load_state() {
    PREV_HOST="" PREV_TLS="" PREV_PORT="" PREV_SAN="" PREV_SSH_FROM="" PREV_USER=""
    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        . "$STATE_FILE"
    fi
}

save_state() {
    {
        echo "# Written by mcutie-chat install.sh; used as defaults on re-run"
        printf 'PREV_HOST=%q\nPREV_TLS=%q\nPREV_PORT=%q\nPREV_SAN=%q\nPREV_SSH_FROM=%q\nPREV_USER=%q\n' \
            "$HOST" "$TLS_MODE" "$PORT" "$SAN" "$SSH_FROM" "$MQTT_USER"
    } > "$STATE_FILE"
    chmod 600 "$STATE_FILE"
}

# ---------------------------------------------------------------- questions
gather_answers() {
    step "Questions (press Enter to accept the default)"
    local detected default_tls default_port
    detected=$(detect_ip || true)

    ask HOST "Broker address clients will use (domain name or public IP)" \
        "${PREV_HOST:-$detected}" --host "$OPT_HOST"
    HOST=${HOST,,}
    if is_ip "$HOST"; then
        HOST_IS_IP=1
        if ! is_public "$HOST"; then
            warn "$HOST is a private/local address: only devices on that network can reach this broker."
        fi
    elif is_domain "$HOST"; then
        HOST_IS_IP=0
    else
        die "\"$HOST\" isn't a valid IP address or domain name."
    fi

    # Default: the previous mode if it still fits this address, else Let's Encrypt for a domain
    # and self-signed for an IP
    if [[ -n "$PREV_TLS" && ! ( $HOST_IS_IP -eq 1 && $PREV_TLS == letsencrypt ) ]]; then default_tls=$PREV_TLS
    elif [[ $HOST_IS_IP -eq 1 ]]; then default_tls=selfsigned
    else default_tls=letsencrypt; fi
    say "TLS options: letsencrypt (domain names only), selfsigned (your own CA, works with IPs), none"
    ask TLS_MODE "TLS mode" "$default_tls" --tls "$OPT_TLS"
    TLS_MODE=${TLS_MODE,,}
    case "$TLS_MODE" in
        letsencrypt)
            [[ $HOST_IS_IP -eq 0 ]] || die "Let's Encrypt needs a domain name, not an IP address." \
                "Use --tls selfsigned for an IP, or point a domain at this server first." ;;
        selfsigned) ;;
        none) warn "Without TLS, MQTT passwords and room metadata cross the network in clear text." ;;
        *) die "Unknown TLS mode \"$TLS_MODE\"." "Use letsencrypt, selfsigned or none." ;;
    esac

    if [[ $TLS_MODE == none ]]; then default_port=1883; else default_port=8883; fi
    [[ -n "$PREV_PORT" && "$PREV_TLS" == "$TLS_MODE" ]] && default_port=$PREV_PORT
    ask PORT "Broker port" "$default_port" --port "$OPT_PORT"
    is_port "$PORT" || die "\"$PORT\" isn't a valid port (1-65535)."
    PORT=$((10#$PORT))

    # Certificate names: the address, plus (self-signed, domain) the detected IP if wanted
    SAN=""
    if [[ $TLS_MODE == selfsigned ]]; then
        if [[ $HOST_IS_IP -eq 1 ]]; then SAN="IP:$HOST"
        else
            SAN="DNS:$HOST"
            local by_ip_default=n
            [[ ",$PREV_SAN," == *",IP:$detected,"* ]] && by_ip_default=y
            if [[ -n "$detected" ]] && ask_yn "Also allow clients to connect by IP $detected?" "$by_ip_default"; then
                SAN="$SAN,IP:$detected"
            fi
        fi
    fi

    if [[ $TLS_MODE == letsencrypt ]]; then
        if [[ -n "$OPT_EMAIL" ]]; then LE_EMAIL=$OPT_EMAIL
        elif interactive; then read -r -p "Email for Let's Encrypt expiry notices (optional): " LE_EMAIL
        else LE_EMAIL=""; fi
        if [[ -n "$LE_EMAIL" && ! $LE_EMAIL =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
            die "\"$LE_EMAIL\" doesn't look like an email address."
        fi
    fi

    ask MQTT_USER "MQTT username" "$PREV_USER" --user "$OPT_USER"
    valid_user "$MQTT_USER" || die "Invalid username \"$MQTT_USER\"." \
        "Use 1-64 letters, digits or . _ @ - (no spaces or colons)."
    SET_PASSWORD=1
    if user_exists "$MQTT_USER" && [[ -z "${MQTT_PASSWORD:-}" ]] \
            && ask_yn "User $MQTT_USER already exists. Keep the current password?" y; then
        SET_PASSWORD=0
    fi
    if [[ $SET_PASSWORD -eq 1 ]]; then ask_password MQTT_PASS "$MQTT_USER"; fi

    ask SSH_FROM "Allow SSH from (IP/CIDR to restrict, or \"any\")" "${PREV_SSH_FROM:-any}" --ssh-from "$OPT_SSH_FROM"
    if [[ ${SSH_FROM,,} == any ]]; then SSH_FROM=any
    else
        is_cidr "$SSH_FROM" || die "\"$SSH_FROM\" isn't a valid IP address or CIDR (e.g. 203.0.113.7 or 203.0.113.0/24)."
        check_ssh_lockout
    fi
}

# Refuse an SSH restriction that would cut off a currently connected SSH session
check_ssh_lockout() {
    local peers peer outside=()
    peers=$(ss -Htn state established 2>/dev/null \
        | awk -v p=":$(ssh_ports | head -1)" '$3 ~ p"$" {print $4}' | sed -E 's/^\[?([^]]*)\]?:[0-9]+$/\1/' | sort -u)
    for peer in $peers; do
        peer=${peer#::ffff:}
        in_cidr "$peer" "$SSH_FROM" || outside+=("$peer")
    done
    if [[ ${#outside[@]} -gt 0 ]]; then
        die "Restricting SSH to $SSH_FROM would lock out the current SSH session(s) from: ${outside[*]}" \
            "Use a range that includes your current IP, or \"any\"."
    fi
}

ssh_ports() {
    local ports
    ports=$(sshd -T 2>/dev/null | awk '$1 == "port" {print $2}' || true)
    printf '%s\n' "${ports:-22}"
}

# ---------------------------------------------------------------- TLS
san_of_cert() {
    openssl x509 -in "$1" -noout -ext subjectAltName 2>/dev/null | tail -n +2 \
        | tr ',' '\n' | sed -E 's/^ *//; s/^IP Address:/IP:/' | grep -v '^$' | sort | paste -sd, -
}
sorted_san() { tr ',' '\n' <<<"$1" | sort | paste -sd, -; }

setup_selfsigned() {
    step "Self-signed TLS"
    install -d -m 700 -o root -g root "$CA_DIR"
    install -d -m 755 "$CERT_DIR"

    if [[ $NEW_CA -eq 1 && -f "$CA_PEM" ]]; then
        warn "Replacing the CA: every app/user must re-paste the new CA or re-scan a new Room QR."
        if interactive && ! ask_yn "Replace the existing CA?" n; then die "Cancelled; nothing changed."; fi
        local stamp; stamp=$(date +%Y%m%d-%H%M%S)
        mv "$CA_PEM" "$CA_DIR/ca.pem.replaced-$stamp"
        [[ -f "$CA_KEY" ]] && mv "$CA_KEY" "$CA_DIR/ca.key.replaced-$stamp"
        rm -f "$SRV_PEM" "$SRV_KEY"
    fi

    if [[ ! -f "$CA_PEM" ]]; then
        openssl ecparam -name prime256v1 -genkey -noout -out "$CA_KEY"
        chmod 600 "$CA_KEY"
        openssl req -x509 -new -key "$CA_KEY" -sha256 -days "$CERT_DAYS" \
            -subj "/CN=Mcutie Chat broker CA ($HOST)" \
            -addext "basicConstraints=critical,CA:TRUE" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" \
            -addext "subjectKeyIdentifier=hash" -out "$CA_PEM"
        chmod 644 "$CA_PEM"
        ok "created a new EC P-256 CA (valid $CERT_DAYS days)"
    else
        ok "reusing the existing CA ($(openssl x509 -in "$CA_PEM" -noout -enddate | cut -d= -f2))"
    fi

    local reason=""
    if [[ ! -f "$SRV_PEM" || ! -f "$SRV_KEY" ]]; then reason="no broker certificate yet"
    elif ! openssl verify -x509_strict -CAfile "$CA_PEM" "$SRV_PEM" >/dev/null 2>&1; then reason="not signed by the current CA"
    elif [[ "$(san_of_cert "$SRV_PEM")" != "$(sorted_san "$SAN")" ]]; then reason="address changed ($(san_of_cert "$SRV_PEM") -> $(sorted_san "$SAN"))"
    elif ! openssl x509 -in "$SRV_PEM" -noout -checkend $((30 * 86400)) >/dev/null; then reason="expires within 30 days"
    fi

    if [[ -n "$reason" ]]; then
        [[ -f "$CA_KEY" ]] || die "The broker certificate needs reissuing ($reason), but the CA private key was removed from this server." \
            "Restore $CA_KEY from your offline backup, or re-run with --new-ca (everyone then re-pastes the CA / re-scans)."
        local ca_end_epoch now days
        ca_end_epoch=$(date -d "$(openssl x509 -in "$CA_PEM" -noout -enddate | cut -d= -f2)" +%s)
        now=$(date +%s)
        days=$(( (ca_end_epoch - now) / 86400 - 1 ))
        (( days > CERT_DAYS )) && days=$CERT_DAYS
        (( days >= 31 )) || die "The CA expires in $days days, too soon to issue a broker certificate." "Re-run with --new-ca."
        local ext="$TMP_DIR/server.ext"
        printf '%s\n' "basicConstraints=critical,CA:FALSE" "keyUsage=critical,digitalSignature" \
            "extendedKeyUsage=serverAuth" "subjectAltName=$SAN" "subjectKeyIdentifier=hash" \
            "authorityKeyIdentifier=keyid" > "$ext"
        openssl ecparam -name prime256v1 -genkey -noout -out "$TMP_DIR/server.key"
        openssl req -new -key "$TMP_DIR/server.key" -subj "/CN=$HOST" -out "$TMP_DIR/server.csr"
        openssl x509 -req -in "$TMP_DIR/server.csr" -CA "$CA_PEM" -CAkey "$CA_KEY" -CAcreateserial \
            -CAserial "$CA_DIR/ca.srl" -sha256 -days "$days" -extfile "$ext" -out "$TMP_DIR/server.pem" 2>/dev/null
        openssl verify -x509_strict -CAfile "$CA_PEM" "$TMP_DIR/server.pem" >/dev/null \
            || die "The new broker certificate failed strict verification." "This is a bug in the installer; please report it."
        install -m 640 -o root -g mosquitto "$TMP_DIR/server.key" "$SRV_KEY"
        install -m 644 -o root -g root "$TMP_DIR/server.pem" "$SRV_PEM"
        ok "issued broker certificate for $SAN ($reason; valid $days days)"
    else
        ok "broker certificate is current for $SAN"
    fi
    install -m 644 -o root -g root "$CA_PEM" "$SRV_CA"
}

setup_letsencrypt() {
    step "Let's Encrypt TLS"
    install -d -m 755 "$CERT_DIR" "$(dirname "$LE_HOOK")"
    local my_ip resolved
    my_ip=$(detect_ip || true)
    resolved=$(getent ahostsv4 "$HOST" | awk '{print $1}' | sort -u | paste -sd' ' -)
    [[ -n "$resolved" ]] || die "$HOST doesn't resolve in DNS." "Create an A record pointing at this server, wait for it to propagate, then re-run."
    if [[ -n "$my_ip" && " $resolved " != *" $my_ip "* ]]; then
        warn "$HOST resolves to $resolved, not this server's address $my_ip. Issuance will fail unless traffic reaches this server (e.g. through NAT)."
    fi

    # Renewal hook: copy the renewed cert where mosquitto (as user mosquitto) can read it, then restart
    cat > "$LE_HOOK" <<EOF
#!/bin/sh
# Installed by mcutie-chat install.sh: copy renewed certificates for mosquitto and restart it.
set -e
LINEAGE="\${RENEWED_LINEAGE:-/etc/letsencrypt/live/$HOST}"
[ "\$LINEAGE" = "/etc/letsencrypt/live/$HOST" ] || exit 0
install -m 644 -o root -g root "\$LINEAGE/fullchain.pem" "$SRV_PEM"
install -m 644 -o root -g root "\$LINEAGE/chain.pem" "$SRV_CA"
install -m 640 -o root -g mosquitto "\$LINEAGE/privkey.pem" "$SRV_KEY"
systemctl restart mosquitto
EOF
    chmod 755 "$LE_HOOK"

    local email_args=(--register-unsafely-without-email)
    [[ -n "${LE_EMAIL:-}" ]] && email_args=(-m "$LE_EMAIL")
    if interactive; then
        say "Let's Encrypt requires agreeing to its Subscriber Agreement: https://letsencrypt.org/repository/"
        ask_yn "Agree and request a certificate for $HOST?" y || die "Cancelled; no certificate requested."
    fi
    say "Requesting a certificate (port 80 is opened only while certbot runs)..."
    certbot certonly --standalone --non-interactive --agree-tos --keep-until-expiring \
        "${email_args[@]}" -d "$HOST" \
        --pre-hook "ufw allow 80/tcp" --post-hook "ufw delete allow 80/tcp" \
        || die "certbot couldn't get a certificate for $HOST." \
               "Check that $HOST points here, that port 80 is reachable from the internet (cloud firewall too), and see /var/log/letsencrypt/letsencrypt.log."
    RENEWED_LINEAGE="/etc/letsencrypt/live/$HOST" "$LE_HOOK" >/dev/null 2>&1 || true
    [[ -f "$SRV_PEM" ]] || die "Copying the certificate for mosquitto failed." "Run $LE_HOOK manually to see why."
    ok "certificate for $HOST installed; renewals copy it and restart mosquitto ($LE_HOOK)"
}

# ---------------------------------------------------------------- mosquitto config
write_config() {
    step "Configuring mosquitto"
    local other
    other=$(grep -lE '^\s*(listener|port|allow_anonymous|password_file)\b' /etc/mosquitto/conf.d/*.conf 2>/dev/null \
        | grep -v "^$CONF_FILE$" || true)
    [[ -z "$other" ]] || warn "Other config files also set listeners/auth and may conflict: $other"

    if [[ $SET_PASSWORD -eq 1 ]]; then
        set_password "$MQTT_USER" "$MQTT_PASS"
        ok "MQTT user $MQTT_USER password set"
    else
        ok "MQTT user $MQTT_USER kept"
    fi

    local tmp="$TMP_DIR/mcutie-chat.conf"
    {
        echo "# Managed by mcutie-chat install.sh - re-run the installer to change it."
        echo "per_listener_settings false"
        echo "allow_anonymous false"
        echo "password_file $PASSWD_FILE"
        echo ""
        echo "listener $PORT"
        if [[ $TLS_MODE != none ]]; then
            echo "cafile $SRV_CA"
            echo "certfile $SRV_PEM"
            echo "keyfile $SRV_KEY"
            echo "tls_version tlsv1.2"
        fi
    } > "$tmp"
    install -m 644 -o root -g root "$tmp" "$CONF_FILE"
    ok "wrote $CONF_FILE (listener $PORT, TLS: $TLS_MODE, anonymous access off)"
}

# ---------------------------------------------------------------- firewall
configure_ufw() {
    step "Configuring the firewall (ufw)"
    local p
    for p in $(ssh_ports); do
        if [[ $SSH_FROM == any ]]; then
            ufw allow "$p/tcp" >/dev/null
        else
            ufw allow from "$SSH_FROM" to any port "$p" proto tcp >/dev/null
            # Only now drop unrestricted SSH rules, so there's never a moment without SSH access
            ufw delete allow "$p/tcp" >/dev/null 2>&1 || true
            ufw delete allow OpenSSH >/dev/null 2>&1 || true
        fi
        if [[ -n "$PREV_SSH_FROM" && "$PREV_SSH_FROM" != any && "$PREV_SSH_FROM" != "$SSH_FROM" ]]; then
            ufw delete allow from "$PREV_SSH_FROM" to any port "$p" proto tcp >/dev/null 2>&1 || true
        fi
    done
    ufw allow "$PORT/tcp" >/dev/null
    if [[ -n "$PREV_PORT" && "$PREV_PORT" != "$PORT" ]]; then
        ufw delete allow "$PREV_PORT/tcp" >/dev/null 2>&1 || true
        ok "removed the old broker port $PREV_PORT"
    fi
    ufw --force enable >/dev/null
    ok "SSH allowed from $SSH_FROM, broker port $PORT/tcp open, ufw enabled"
}

# ---------------------------------------------------------------- service + self-test
restart_mosquitto() {
    step "Starting mosquitto"
    systemctl enable mosquitto >/dev/null 2>&1
    if ! systemctl restart mosquitto || ! systemctl is-active --quiet mosquitto; then
        journalctl -u mosquitto -n 20 --no-pager >&2 || true
        die "mosquitto failed to start with the new configuration (log above)." "Fix the cause shown in the log and re-run."
    fi
    ok "mosquitto is running"
}

self_test() {
    step "Self-test: publish and subscribe on $HOST:$PORT (TLS: $TLS_MODE)"
    local pass
    SELFTEST_USER="mcutie-selftest-$(openssl rand -hex 4)"
    pass=$(openssl rand -hex 16)
    set_password "$SELFTEST_USER" "$pass"
    systemctl reload mosquitto
    sleep 1
    client_opts "$TMP_DIR/auth" "$SELFTEST_USER" "$pass"
    roundtrip "$TMP_DIR/auth" \
        || die "Self-test failed: a message didn't make it through $HOST:$PORT." \
               "The client error is shown above. For TLS, the address must match the certificate; check the firewall too."
    ok "authenticated publish/subscribe works"

    mkdir -p "$TMP_DIR/anon"
    local tls_args=()
    mapfile -t tls_args < <(tls_client_args)
    if XDG_CONFIG_HOME="$TMP_DIR/anon" mosquitto_pub -h "$HOST" -p "$PORT" "${tls_args[@]}" \
            -t mcutie-chat/selftest/anon -m x >/dev/null 2>&1; then
        die "Self-test failed: an anonymous client was allowed to publish." "Check for other mosquitto config files allowing anonymous access."
    fi
    ok "anonymous clients are refused"

    passwd_update "$SELFTEST_USER" delete
    SELFTEST_USER=""
    systemctl reload mosquitto
}

# ---------------------------------------------------------------- summary + CA key
summary() {
    step "Done"
    local tls_on=No
    [[ $TLS_MODE != none ]] && tls_on=Yes
    cat <<EOF

  Broker address : $HOST
  Port           : $PORT
  TLS            : $TLS_MODE
  MQTT users     : $(cut -d: -f1 "$PASSWD_FILE" | paste -sd' ' -)

  In the Mcutie Chat app (connection screen):
    Server Address : $HOST
    Port           : $PORT
    Use TLS        : $tls_on
    MQTT Username  : $MQTT_USER (and its password)
EOF
    case "$TLS_MODE" in
        selfsigned)
            cat <<EOF
    Broker CA certificate: paste this whole block (or load it from a file on desktop).
    Then share the room with others by Room QR, which carries the CA.

$(cat "$CA_PEM")
EOF
            ;;
        letsencrypt) say "    Broker CA certificate: leave empty (Let's Encrypt is publicly trusted)." ;;
        none) say "    No TLS: the MQTT password crosses the network in clear text." ;;
    esac
    say ""
    say "Add more MQTT users later with:  sudo ./install.sh --add-user"
}

offer_ca_key_removal() {
    [[ $TLS_MODE == selfsigned && -f "$CA_KEY" ]] || return 0
    say ""
    warn "The CA private key is stored on this server: $CA_KEY"
    say "  Anyone who gets it can impersonate this broker to every app that trusts the CA."
    say "  Keeping it offline is safer. It's only needed to issue a new broker certificate,"
    say "  which happens when the address changes or in ~10 years."
    interactive || { say "  (Non-interactive run: the key was kept. Re-run interactively to back it up and remove it.)"; return 0; }
    if ask_yn "Print the CA private key for an offline backup, then delete it from this server?" n; then
        say ""
        say "----- copy everything between the lines into a password manager or offline storage -----"
        cat "$CA_KEY"
        say "-----------------------------------------------------------------------------------------"
        local confirm
        read -r -p "Type DELETE once you've saved it (anything else keeps it): " confirm
        if [[ $confirm == DELETE ]]; then
            shred -u "$CA_KEY"
            ok "CA private key deleted from this server."
            say "  Note: a future broker certificate (new address, or in ~10 years) then needs either"
            say "  this key restored to $CA_KEY, or --new-ca, which makes everyone re-paste/re-scan."
        else
            say "  Kept $CA_KEY."
        fi
    fi
}

# ---------------------------------------------------------------- --add-user
add_user() {
    preflight
    load_state
    [[ -f "$STATE_FILE" && -f "$CONF_FILE" ]] || die "No Mcutie Chat broker is installed here yet." "Run sudo ./install.sh first."
    HOST=$PREV_HOST TLS_MODE=$PREV_TLS PORT=$PREV_PORT
    step "Add or update an MQTT user"
    local name pass
    ask name "New MQTT username" "" "--add-user NAME" "$OPT_USER"
    valid_user "$name" || die "Invalid username \"$name\"." "Use 1-64 letters, digits or . _ @ - (no spaces or colons)."
    if user_exists "$name"; then
        warn "User $name already exists: this sets a new password."
        if interactive && ! ask_yn "Continue?" y; then die "Cancelled; nothing changed."; fi
    fi
    ask_password pass "$name"
    set_password "$name" "$pass"
    systemctl reload mosquitto
    sleep 1
    client_opts "$TMP_DIR/auth" "$name" "$pass"
    roundtrip "$TMP_DIR/auth" || die "User $name was saved, but logging in as $name failed (error above)."
    ok "user $name can log in and publish/subscribe on $HOST:$PORT"
}

# ---------------------------------------------------------------- main
main() {
    preflight
    install_packages mosquitto mosquitto-clients ufw openssl python3
    load_state
    gather_answers
    [[ $TLS_MODE == letsencrypt ]] && install_packages certbot
    case "$TLS_MODE" in
        selfsigned)  setup_selfsigned ;;
        letsencrypt) setup_letsencrypt ;;
    esac
    write_config
    configure_ufw
    restart_mosquitto
    self_test
    save_state
    summary
    offer_ca_key_removal
}

if [[ $MODE == add-user ]]; then add_user; else main; fi
