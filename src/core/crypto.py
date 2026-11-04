"""AES-GCM encryption for account secrets (section 14)."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import get_settings


class SecretBox:
    def __init__(self, key_b64: str | None = None):
        raw = key_b64 if key_b64 is not None else get_settings().master_key
        if not raw:
            raise RuntimeError("YF_MASTER_KEY is not configured; refusing to store secrets in clear")
        try:
            self._key = base64.urlsafe_b64decode(raw)
        except Exception:  # allow a plain 32-byte passphrase in development
            self._key = raw.encode("utf-8")[:32].ljust(32, b"0")
        if len(self._key) not in (16, 24, 32):
            raise ValueError("master key must decode to 16/24/32 bytes")
        self._aead = AESGCM(self._key)

    def encrypt(self, plaintext: str, aad: bytes | None = None) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad)

    def decrypt(self, blob: bytes, aad: bytes | None = None) -> str:
        return self._aead.decrypt(blob[:12], blob[12:], aad).decode("utf-8")


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode("ascii")
