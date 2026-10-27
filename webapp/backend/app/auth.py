"""Multi-user accounts: password hashing, signed bearer tokens, user CRUD.

Stdlib-only for hashing/tokens on purpose (no `bcrypt`/`passlib`/`pyjwt`
dependency) — password hashing is PBKDF2-HMAC-SHA256 via `hashlib`
(NIST-recommended, no C extension to build on a bare Windows box for the
home deploy), tokens are a plain HMAC-signed payload via `hmac`/`secrets`,
not a full JWT (no need for JWT's algorithm-negotiation surface here — this
token is only ever read by this same backend).

Shares the same DB as `projects.py` (one `users` table alongside
`projects`) — see `app/db.py` for which storage backend that resolves to.

Signing secret: if this ever runs against Postgres, `AUTH_SECRET_KEY` (env
var) MUST be set explicitly — Postgres is the signal that state lives off
this one box, which is also exactly the scenario where a second process
or instance could exist, and a file-based secret would differ per
instance, with every other instance rejecting tokens it didn't sign. The
home deploy (one process, durable disk, SQLite) keeps the file-based
secret for simplicity — no secret-management step needed to get it
running.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

from . import db
from .projects import _conn as _projects_conn  # same DB, shared connection helper

SECRET_PATH = Path(__file__).resolve().parent.parent / "data" / "secret.key"
TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
PBKDF2_ITERATIONS = 200_000

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")


def _conn():
    conn = _projects_conn()  # ensures projects table + parent dir/DB exist too
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            salt TEXT NOT NULL,
            pw_hash TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        )"""
    )
    # Added for /api/auth/logout: bumping this invalidates every token issued
    # before the bump, since each token carries the version it was signed
    # with and verify_token rejects a mismatch — see bump_token_version.
    db.add_column_if_missing(conn, "users", "token_version", "INTEGER NOT NULL DEFAULT 0")
    return conn


def _get_secret() -> bytes:
    env_secret = os.environ.get("AUTH_SECRET_KEY")
    if env_secret:
        return bytes.fromhex(env_secret) if _looks_like_hex(env_secret) else env_secret.encode("utf-8")
    if db.BACKEND == "postgres":
        raise RuntimeError(
            "AUTH_SECRET_KEY env var is required when running against Postgres "
            "(local disk isn't shared across instances or restarts) — see "
            "webapp/deploy/.env.example"
        )
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32))
    return bytes.fromhex(SECRET_PATH.read_text().strip())


def _looks_like_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return True
    except ValueError:
        return False


# ---------- passwords ----------
def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, expected_hash_hex: str) -> bool:
    _, digest_hex = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest_hex, expected_hash_hex)


# ---------- tokens (HMAC-signed, not encrypted — payload is id/username/expiry/version) ----------
def make_token(user_id: str, username: str, token_version: int) -> str:
    expiry = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{user_id}:{username}:{expiry}:{token_version}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    sig = hmac.new(_get_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> Optional[dict]:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected_sig = hmac.new(_get_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        user_id, username, expiry, token_version = payload.split(":", 3)
        expiry = int(expiry)
        token_version = int(token_version)
    except (ValueError, UnicodeDecodeError):
        return None
    if time.time() > expiry:
        return None
    # Cryptographically valid and unexpired isn't enough on its own — a token
    # signed before the user's last /api/auth/logout must still be rejected,
    # so this is the one place verify_token needs a DB read rather than
    # staying pure HMAC/expiry math.
    current = get_user_by_id(user_id)
    if current is None or current["token_version"] != token_version:
        return None
    return {"user_id": user_id, "username": username}


# ---------- user CRUD ----------
def validate_username(username: str) -> Optional[str]:
    if not USERNAME_RE.match(username):
        return "Username must be 3-32 characters: letters, numbers, underscore, dot, or dash."
    return None


def validate_password(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 256:
        return "Password is too long."
    return None


def create_user(username: str, password: str) -> dict:
    salt_hex, hash_hex = hash_password(password)
    uid = uuid.uuid4().hex
    now = time.time()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, username, salt, pw_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (uid, username, salt_hex, hash_hex, now),
            )
        except Exception as exc:
            if db.is_integrity_error(exc):
                raise ValueError(f"Username '{username}' is already taken") from None
            raise
    return {"id": uid, "username": username}


def get_user_by_username(username: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, username, salt, pw_hash, token_version FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "salt": row[2], "pw_hash": row[3], "token_version": row[4]}


def get_user_by_id(user_id: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, username, token_version FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "token_version": row[2]}


def bump_token_version(user_id: str) -> int:
    """Invalidates every token issued for this user before now (see
    verify_token). This app has no per-device session table, so there's no
    narrower "log out just this device" to offer — every token is already
    anonymous w.r.t. which device signed in, so any revocation is global."""
    with _conn() as conn:
        conn.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?", (user_id,))
        row = conn.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()
    return row[0] if row else 0
