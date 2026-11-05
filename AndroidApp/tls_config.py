"""TLS settings for the broker connection (see PROTOCOL.md, "TLS trust rules").

- Room has a CA (PEM): trust only that CA (pinned), never the public list.
- No CA: verify against the bundled certifi list (publicly trusted brokers).
- There is no unverified mode: hostname checks and certificate verification
  are always on.
"""
import datetime
import re
import ssl

PEM_BLOCK_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----")


def validate_ca_pem(text):
    """Return normalized PEM for exactly one CA certificate, or raise ValueError."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    text = (text or "").strip()
    if "PRIVATE KEY" in text:
        raise ValueError("That's a private key. Paste the CA certificate, never a key.")
    blocks = PEM_BLOCK_RE.findall(text)
    if not blocks:
        raise ValueError("Not a PEM certificate (expected -----BEGIN CERTIFICATE-----).")
    if len(blocks) > 1:
        raise ValueError("Paste exactly one CA certificate, not a chain or bundle.")
    try:
        cert = x509.load_pem_x509_certificate(blocks[0].encode())
    except ValueError:
        raise ValueError("The CA certificate couldn't be parsed.")
    try:
        is_ca = cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        is_ca = False
    if not is_ca:
        raise ValueError("Not a CA certificate (basicConstraints CA:TRUE is missing). "
                         "Use the CA that signed the broker's certificate.")
    if cert.not_valid_after_utc < datetime.datetime.now(datetime.timezone.utc):
        raise ValueError(f"The CA certificate expired on {cert.not_valid_after_utc:%Y-%m-%d}.")
    return cert.public_bytes(Encoding.PEM).decode()


def describe_ca(pem):
    """Short human description, e.g. 'CN=My Broker CA, EC P-256, expires 2036-11-04'."""
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    from cryptography.x509.oid import NameOID

    cert = x509.load_pem_x509_certificate(pem.encode())
    cns = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    name = f"CN={cns[0].value}" if cns else cert.subject.rfc4514_string() or "(no name)"
    key = cert.public_key()
    if isinstance(key, ec.EllipticCurvePublicKey):
        curves = {"secp256r1": "P-256", "secp384r1": "P-384", "secp521r1": "P-521"}
        kind = f"EC {curves.get(key.curve.name, key.curve.name)}"
    elif isinstance(key, rsa.RSAPublicKey):
        kind = f"RSA-{key.key_size}"
    else:
        kind = type(key).__name__
    return f"{name}, {kind}, expires {cert.not_valid_after_utc:%Y-%m-%d}"


def make_ssl_context(ca_pem=None):
    """Verified TLS client context: pinned to ca_pem if given, else the certifi list."""
    if ca_pem:
        ctx = ssl.create_default_context(cadata=validate_ca_pem(ca_pem))
    else:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # Same strictness on every Python (3.13+ default; 3.12 desktop isn't)
    ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    return ctx


if __name__ == "__main__":
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID

    def make_cert(cn, ca=True, days=3650, start_days=0):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=start_days)
        builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(days=1))
                   .not_valid_after(now + datetime.timedelta(days=days)))
        if ca:
            builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        return builder.sign(key, hashes.SHA256()).public_bytes(Encoding.PEM).decode()

    def rejects(text, needle):
        try:
            validate_ca_pem(text)
        except ValueError as e:
            assert needle in str(e), (needle, str(e))
            return
        raise AssertionError("accepted")

    good = make_cert("Test Broker CA")
    assert validate_ca_pem("  \n" + good + "\n") == good
    desc = describe_ca(good)
    assert desc.startswith("CN=Test Broker CA, EC P-256, expires "), desc
    rejects(make_cert("Leaf", ca=False), "Not a CA certificate")
    rejects(good + good, "exactly one")
    rejects("hello", "Not a PEM")
    rejects("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", "private key")
    rejects(make_cert("Old CA", days=1, start_days=-30), "expired")

    pinned = make_ssl_context(good)
    assert len(pinned.get_ca_certs()) == 1, "pinned context must trust only the room CA"
    assert pinned.check_hostname and pinned.verify_mode == ssl.CERT_REQUIRED
    public = make_ssl_context()
    assert len(public.get_ca_certs()) > 50, "certifi list should be loaded"
    assert public.verify_flags & ssl.VERIFY_X509_STRICT
    print("describe_ca:", desc)
    print("all self-tests passed")
