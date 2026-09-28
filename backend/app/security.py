"""Password hashing, JWT sessions, and signed media URLs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import jwt

from .config import JWT_TTL_SECONDS, MEDIA_TOKEN_TTL, SECRET

PBKDF2_ITERS = 310_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2_sha256${PBKDF2_ITERS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def make_jwt(user_id: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + JWT_TTL_SECONDS, "typ": "session"}, SECRET, "HS256")


def read_jwt(token: str) -> str | None:
    try:
        data = jwt.decode(token, SECRET, algorithms=["HS256"])
        return data["sub"] if data.get("typ") == "session" else None
    except jwt.PyJWTError:
        return None


def sign_media(user_id: str, resource: str, ttl: int = MEDIA_TOKEN_TTL) -> str:
    """Short-lived HMAC token for <video src>, since iOS Safari can't attach auth headers to media requests."""
    # bucketed expiry → identical URLs for ~30 min, so the player/browser cache isn't invalidated on every refresh
    exp = (int(time.time()) // 1800) * 1800 + ttl + 1800
    msg = f"{user_id}|{resource}|{exp}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()[:18]).decode()
    return f"{user_id}.{exp}.{sig}"


def verify_media(token: str, resource: str) -> str | None:
    try:
        user_id, exp_s, sig = token.split(".")
        exp = int(exp_s)
    except ValueError:
        return None
    if exp < time.time():
        return None
    msg = f"{user_id}|{resource}|{exp}".encode()
    good = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()[:18]).decode()
    return user_id if hmac.compare_digest(good, sig) else None
