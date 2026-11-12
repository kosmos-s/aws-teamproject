import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session
from .models import User


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, encoded):
    _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(engine, username, password, role="member"):
    if not username.strip() or len(username) > 80 or len(password) < 8 or role not in {"admin", "member", "viewer"}:
        raise ValueError("username, password (8+ characters), or role invalid")
    with Session(engine) as db:
        db.add(User(username=username, password_hash=password_hash(password), role=role))
        db.commit()


# --- TOTP (RFC 6238, 30 s, 6 digits, SHA-1) using only the standard library ---
import base64 as _b64
import struct as _struct
import time as _time


def totp_new_secret():
    return _b64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret, at=None, step=30, digits=6):
    key = _b64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else _time.time()) // step)
    mac = hmac.new(key, _struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = (_struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(value).zfill(digits)


def totp_verify(secret, code, window=1, at=None):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return False
    now = at if at is not None else _time.time()
    return any(hmac.compare_digest(totp_code(secret, now + k * 30), code) for k in range(-window, window + 1))
