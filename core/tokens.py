"""
=====================================================================
JWT access token + opaque refresh token.

Kontrakt eski Next.js backend'i bilan bir xil saqlangan, shuning uchun
Flutter ilovasi (app_flutter/lib/core/api.dart) hech qanday oʻzgarishsiz
ishlashda davom etadi:

    POST /api/auth/login    → {access, refresh, user}
    POST /api/auth/refresh  → {access}
    Authorization: Bearer <access>

Access token — HS256 JWT, ichida faqat `sub` (ishchi id) va muddat.
Refresh token — tasodifiy opaque satr; bazada faqat SHA-256 hash'i
saqlanadi (core.models.RefreshToken).
=====================================================================
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from core.models import RefreshToken, Worker

ALGORITHM = "HS256"


# ---------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------

def access_muddati() -> timedelta:
    return timedelta(minutes=settings.JWT_ACCESS_MIN)


def refresh_muddati() -> timedelta:
    return timedelta(days=settings.JWT_REFRESH_DAYS)


def make_access(worker: Worker) -> str:
    now = timezone.now()
    payload = {
        "sub": str(worker.id),
        "tabel": worker.tabel,
        "roles": worker.roles or [],
        "iat": int(now.timestamp()),
        "exp": int((now + access_muddati()).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def read_access(token: str) -> dict | None:
    """Access token'ni tekshirib, ichidagi maʼlumotni qaytaradi. Xato boʻlsa None."""
    if not token:
        return None
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def make_refresh(worker: Worker, user_agent: str = "") -> str:
    """Yangi refresh token yaratadi va uning hash'ini bazaga yozadi."""
    token = secrets.token_urlsafe(32)
    RefreshToken.objects.create(
        worker=worker,
        token_hash=_hash(token),
        expires_at=timezone.now() + refresh_muddati(),
        user_agent=(user_agent or "")[:255],
    )
    return token


def read_refresh(token: str) -> RefreshToken | None:
    """Refresh token yozuvini topadi (yaroqli boʻlsa)."""
    if not token:
        return None
    row = (
        RefreshToken.objects.select_related("worker")
        .filter(token_hash=_hash(token))
        .first()
    )
    if row and row.yaroqli:
        return row
    return None


def revoke_refresh(token: str) -> None:
    """Chiqishda — shu tokenni bekor qilish."""
    if not token:
        return
    RefreshToken.objects.filter(token_hash=_hash(token)).update(revoked=True)


def revoke_all(worker: Worker) -> None:
    """Ishchining barcha seanslarini bekor qilish (PIN tiklanganda)."""
    RefreshToken.objects.filter(worker=worker, revoked=False).update(revoked=True)


def tozalash() -> int:
    """Muddati oʻtgan tokenlarni oʻchirish. Xizmat buyrugʻi chaqiradi."""
    adet, _ = RefreshToken.objects.filter(expires_at__lt=timezone.now()).delete()
    return adet


# ---------------------------------------------------------------------
# Juftlikni yaratish
# ---------------------------------------------------------------------

def token_juftligi(worker: Worker, user_agent: str = "") -> dict[str, str]:
    return {
        "access": make_access(worker),
        "refresh": make_refresh(worker, user_agent),
    }
