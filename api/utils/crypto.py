"""Symmetric token encryption helpers (Fernet / AES-128-CBC + HMAC).

Used by BL-1044 Gmail OAuth foundation to encrypt OAuth access / refresh
tokens at rest. The Fernet key is injected via env var (configured on the
Flask app) to allow independent rotation from the generic OAuth token
encryption key used by `api/services/google_oauth.py`.

Keep this module framework-agnostic -- callers pass the key in explicitly so
tests can exercise the primitives without a Flask app context. Route code
resolves the key from `current_app.config["GMAIL_TOKEN_ENCRYPTION_KEY"]`.
"""

from __future__ import annotations

from cryptography.fernet import Fernet


def _coerce_key(key: str | bytes) -> bytes:
    if isinstance(key, bytes):
        return key
    return key.encode()


def encrypt_token(token: str, key: str | bytes) -> bytes:
    """Encrypt `token` with the Fernet `key`.

    Returns raw ciphertext bytes suitable for a BYTEA column.
    Raises ValueError if token is empty or key is falsy.
    """
    if not token:
        raise ValueError("token must be non-empty")
    if not key:
        raise ValueError("encryption key must be configured")
    return Fernet(_coerce_key(key)).encrypt(token.encode())


def decrypt_token(ciphertext: bytes | memoryview, key: str | bytes) -> str:
    """Decrypt `ciphertext` with the Fernet `key`.

    Accepts bytes or memoryview (PostgreSQL psycopg may surface BYTEA as
    memoryview). Raises `cryptography.fernet.InvalidToken` on tampering or
    key mismatch.
    """
    if not ciphertext:
        raise ValueError("ciphertext must be non-empty")
    if not key:
        raise ValueError("encryption key must be configured")
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    return Fernet(_coerce_key(key)).decrypt(ciphertext).decode()


def generate_key() -> str:
    """Generate a fresh Fernet key as a URL-safe base64 string.

    Intended for one-time secret provisioning; do NOT call at runtime.
    """
    return Fernet.generate_key().decode()
