"""
=====================================================================
PIN hash — parol hech qachon ochiq saqlanmaydi.

Format:  "saltHex:hashHex"

Ikki xil algoritm tanib olinadi (eski maʼlumot yoʻqolmasligi uchun):

  1. PBKDF2-SHA256, 100 000 iteratsiya, 32 bayt  ← ASOSIY
     Frontend'dagi lib/pin.ts (Web Crypto) shu formatni yozgan.
     Yangi PIN'lar ham shu formatda saqlanadi.

  2. scrypt (N=16384, r=8, p=1, 32 bayt)         ← ESKI
     Eski Next.js backend'idagi lib/auth.ts (Node crypto) shu
     formatni yozgan. Faqat tekshirish uchun qoʻllab-quvvatlanadi.

Qaysi algoritm ekanini hash uzunligi va prefiksi orqali emas, ketma-ket
urinish orqali aniqlaymiz — ikkala format ham "hex:hex" koʻrinishida.
=====================================================================
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ITER = 100_000
DKLEN = 32
SALT_BYTES = 16

# Node crypto.scryptSync standart parametrlari
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1


def _pbkdf2(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITER, dklen=DKLEN)


def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DKLEN,
        maxmem=64 * 1024 * 1024,
    )


def hash_pin(pin: str) -> str:
    """Yangi PIN hash — PBKDF2-SHA256, brauzer formatiga mos."""
    if not pin:
        raise ValueError("PIN boʻsh boʻlishi mumkin emas")
    salt = secrets.token_bytes(SALT_BYTES)
    return f"{salt.hex()}:{_pbkdf2(pin, salt).hex()}"


def verify_pin(pin: str, stored: str | None) -> bool:
    """
    PIN'ni saqlangan hash bilan solishtirish.

    Avval PBKDF2 (asosiy format), soʻng scrypt (eski format) tekshiriladi.
    Taqqoslash doim doimiy vaqtda (hmac.compare_digest) bajariladi.
    """
    if not pin or not stored or ":" not in stored:
        return False

    salt_hex, _, hash_hex = stored.partition(":")
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False

    if not salt or not expected:
        return False

    if hmac.compare_digest(_pbkdf2(pin, salt), expected):
        return True

    try:
        return hmac.compare_digest(_scrypt(pin, salt), expected)
    except (ValueError, MemoryError):
        return False


def needs_rehash(stored: str | None) -> bool:
    """Eski scrypt formatidagi hash yangilanishi kerakligini bildiradi."""
    if not stored or ":" not in stored:
        return True
    return False


def valid_pin_format(pin: str, uzunlik: int = 4) -> bool:
    """PIN faqat raqamlardan iborat va kerakli uzunlikda boʻlishi shart."""
    return bool(pin) and pin.isdigit() and len(pin) == uzunlik
