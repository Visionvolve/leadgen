"""Unit tests for api/utils/crypto.py (BL-1044 token encryption)."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from api.utils.crypto import decrypt_token, encrypt_token, generate_key


class TestRoundTrip:
    def test_encrypt_decrypt_string_roundtrip(self):
        key = Fernet.generate_key().decode()
        token = "ya29.some-access-token-value"
        ct = encrypt_token(token, key)
        assert isinstance(ct, bytes)
        assert ct != token.encode()
        assert decrypt_token(ct, key) == token

    def test_accepts_bytes_key(self):
        key = Fernet.generate_key()  # bytes
        token = "refresh-token"
        ct = encrypt_token(token, key)
        assert decrypt_token(ct, key) == token

    def test_decrypt_accepts_memoryview(self):
        key = Fernet.generate_key().decode()
        ct = encrypt_token("payload", key)
        mv = memoryview(ct)
        assert decrypt_token(mv, key) == "payload"


class TestErrors:
    def test_empty_token_rejected(self):
        key = Fernet.generate_key().decode()
        with pytest.raises(ValueError, match="token must be non-empty"):
            encrypt_token("", key)

    def test_empty_key_rejected_on_encrypt(self):
        with pytest.raises(ValueError, match="encryption key must be configured"):
            encrypt_token("x", "")

    def test_empty_key_rejected_on_decrypt(self):
        with pytest.raises(ValueError, match="encryption key must be configured"):
            decrypt_token(b"ciphertext", "")

    def test_wrong_key_fails(self):
        k1 = Fernet.generate_key().decode()
        k2 = Fernet.generate_key().decode()
        ct = encrypt_token("secret", k1)
        with pytest.raises(InvalidToken):
            decrypt_token(ct, k2)

    def test_tampered_ciphertext_fails(self):
        key = Fernet.generate_key().decode()
        ct = bytearray(encrypt_token("secret", key))
        ct[-1] ^= 0x01  # flip a bit
        with pytest.raises(InvalidToken):
            decrypt_token(bytes(ct), key)


class TestGenerateKey:
    def test_generate_key_is_usable(self):
        key = generate_key()
        assert isinstance(key, str)
        # Must round-trip through Fernet
        ct = encrypt_token("x", key)
        assert decrypt_token(ct, key) == "x"
