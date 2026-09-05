"""RFC 6238 TOTP (SHA-1, 30s, 6 digits) plus recovery codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import RecoveryCode

PERIOD = 30
DIGITS = 6
WINDOW = 1


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    padded = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**DIGITS)).zfill(DIGITS)


def totp_at(secret: str, for_time: float | None = None) -> str:
    ts = int(for_time if for_time is not None else time.time())
    return _hotp(secret, ts // PERIOD)


def verify_totp(secret: str, code: str, window: int = WINDOW, for_time: float | None = None) -> bool:
    if not secret or not code:
        return False
    cleaned = "".join(ch for ch in str(code) if ch.isdigit())
    if len(cleaned) != DIGITS:
        return False
    ts = int(for_time if for_time is not None else time.time())
    counter = ts // PERIOD
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + delta), cleaned):
            return True
    return False


def provisioning_uri(username: str, secret: str, issuer: str = "Control Center") -> str:
    label = quote(f"{issuer}:{username}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def qr_data_uri(uri: str) -> str:
    import qrcode

    img = qrcode.make(uri, box_size=4, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def twofa_enabled(user) -> bool:
    profile = getattr(user, "profile", None)
    return bool(profile and profile.totp_confirmed_at and profile.totp_secret)


def generate_recovery_codes(count: int = 10) -> list[str]:
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def store_recovery_codes(user, codes: list[str]):
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=user, code_hash=make_password(code.replace("-", "").upper())) for code in codes]
    )


def consume_recovery_code(user, code: str) -> bool:
    cleaned = "".join(ch for ch in (code or "") if ch.isalnum()).upper()
    if len(cleaned) != 8:
        return False
    unused = RecoveryCode.objects.filter(user=user, used_at__isnull=True)
    for row in unused:
        if check_password(cleaned, row.code_hash):
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
            return True
    return False


def clear_twofa(user):
    profile = user.profile
    profile.totp_secret = ""
    profile.totp_confirmed_at = None
    profile.save(update_fields=["totp_secret", "totp_confirmed_at"])
    RecoveryCode.objects.filter(user=user).delete()
