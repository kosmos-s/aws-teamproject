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
