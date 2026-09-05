"""Fernet encryption for secrets at rest (vault, TOTP, site tokens)."""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

_fernet = None
FERNET_PREFIX = "gAAAAA"


def _key_path() -> Path:
    return Path(getattr(settings, "CC_VAULT_KEY_FILE", settings.BASE_DIR / "data" / "vault.key"))


def _load_or_create_key() -> bytes:
    env_key = (os.environ.get("CC_VAULT_KEY") or "").strip()
    if env_key:
        return env_key.encode("utf-8") if not env_key.startswith("gAAAA") else env_key.encode("utf-8")

    path = _key_path()
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            return raw.encode("utf-8")

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.decode("ascii"), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _load_or_create_key()
        _fernet = Fernet(key)
    return _fernet


def looks_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(FERNET_PREFIX)


def encrypt(value: str) -> str:
    if value is None or value == "":
        return value or ""
    if looks_encrypted(value):
        return value
    return get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    if value is None or value == "":
        return value or ""
    try:
        return get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return value


def decrypt_maybe(value: str) -> str:
    if not value or not looks_encrypted(value):
        return value or ""
    return decrypt(value)


class EncryptedTextField(models.TextField):
    description = "Text encrypted at rest with Fernet"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt_maybe(value)

    def to_python(self, value):
        if value is None:
            return value
        return decrypt_maybe(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt(value)
