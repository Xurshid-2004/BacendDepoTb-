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
import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from core.models import Qurilma, RefreshToken, Worker

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


def ishonch_muddati() -> timedelta:
    """Ishonchli telefon uchun muddat — har yangilanishda qaytadan sanaladi."""
    return timedelta(days=settings.QURILMA_ISHONCH_KUN)


def _muddat(qurilma: Qurilma | None) -> timezone.datetime:
    """
    Ishonchli telefonga uzoq muddat, qolganiga qisqa.

    Muddat har rotatsiyada qaytadan boshlanadi (sliding window): telefonini
    kunda ishlatadigan ishchidan PIN boshqa hech qachon soʻralmaydi, uzoq
    vaqt ishlatilmagan token esa oʻzi oʻlib ketadi.
    """
    uzun = bool(qurilma and qurilma.ishonchli and qurilma.mobil)
    return timezone.now() + (ishonch_muddati() if uzun else refresh_muddati())


def make_refresh(
    worker: Worker,
    user_agent: str = "",
    qurilma: Qurilma | None = None,
    zanjir: uuid.UUID | None = None,
) -> str:
    """
    Yangi refresh token yaratadi va uning hash'ini bazaga yozadi.

    `zanjir` berilsa — bu rotatsiya, token oʻsha seansning davomi boʻladi.
    Berilmasa yangi seans boshlanadi.
    """
    token = secrets.token_urlsafe(32)
    RefreshToken.objects.create(
        worker=worker,
        token_hash=_hash(token),
        expires_at=_muddat(qurilma),
        user_agent=(user_agent or "")[:255],
        qurilma=qurilma,
        **({"zanjir": zanjir} if zanjir else {}),
    )
    return token


def read_refresh(token: str) -> RefreshToken | None:
    """Refresh token yozuvini topadi (yaroqli boʻlsa)."""
    if not token:
        return None
    row = (
        RefreshToken.objects.select_related("worker", "qurilma")
        .filter(token_hash=_hash(token))
        .first()
    )
    if row and row.yaroqli:
        return row
    return None


# ---------------------------------------------------------------------
# Rotatsiya va qayta ishlatishni aniqlash
# ---------------------------------------------------------------------

# Rotatsiyadan keyin eski token shu muddat ichida yana kelsa — bu hujum
# emas, balki ikki oyna (yoki qayta yuborilgan soʻrov) bir vaqtda
# yangilagani. Bu oraliq boʻlmasa foydalanuvchi bekordan-bekor chiqib
# ketardi.
TAKROR_ORALIQ = timedelta(seconds=30)


def refresh_holati(token: str) -> tuple[RefreshToken | None, str]:
    """
    Refresh tokenni tekshiradi va holatini aytadi:

      "ok"     — yaroqli, yangilash mumkin
      "takror" — endigina almashtirilgan token qayta keldi (ikki oyna),
                 xavfsiz: yangi juftlik beriladi
      "qayta"  — ancha oldin ALMASHTIRILGAN token ishlatildi. Demak
                 uning nusxasi birovda qolgan — QURILMA BEKOR QILINADI
      "muddat" — muddati oʻtgan
      "yoq"    — topilmadi, yoki chiqish/tiklash bilan bekor qilingan

    Chiqish (logout), admin PIN tiklashi va qurilma oʻchirilishi natijasida
    bekor boʻlgan tokenlar «yoq» deb qaraladi: ular uchun na imtiyoz
    oraligʻi bor, na «hujum» deb hisoblash oʻrinli — foydalanuvchi shunchaki
    qaytadan kirishi kerak.
    """
    if not token:
        return None, "yoq"

    row = (
        RefreshToken.objects.select_related("worker", "qurilma")
        .filter(token_hash=_hash(token))
        .first()
    )
    if not row:
        return None, "yoq"

    if row.expires_at <= timezone.now():
        return row, "muddat"

    if row.revoked:
        # Rotatsiyadan boshqa sabab bilan bekor qilingan — chiqish,
        # PIN tiklash yoki qurilma oʻchirilishi. Oddiy 401.
        if not row.almashtirilgan:
            return row, "yoq"

        oxirgi = row.oxirgi_ishlatilgan
        if oxirgi and timezone.now() - oxirgi <= TAKROR_ORALIQ:
            return row, "takror"
        return row, "qayta"

    return row, "ok"


def rotate_refresh(row: RefreshToken, user_agent: str = "") -> str:
    """
    Eski tokenni bekor qilib, oʻrniga yangisini beradi.

    Shu tufayli oʻgʻirlangan token uzoq yashamaydi: haqiqiy egasi keyingi
    marta yangilaganda oʻgʻirlangan nusxa ishlamay qoladi va aksincha —
    oʻgʻri ishlatsa, egasining soʻrovi «qayta» holatiga tushib butun
    qurilma bekor qilinadi.
    """
    now = timezone.now()
    RefreshToken.objects.filter(pk=row.pk).update(
        revoked=True, almashtirilgan=True, oxirgi_ishlatilgan=now
    )

    qurilma = row.qurilma
    if qurilma:
        Qurilma.objects.filter(pk=qurilma.pk).update(oxirgi_kirish=now)

    return make_refresh(row.worker, user_agent or row.user_agent, qurilma, row.zanjir)


def revoke_qurilma_tokenlari(row: RefreshToken) -> None:
    """
    Token qayta ishlatilgani aniqlanganda — oʻsha qurilmaning barcha
    tokenlarini bekor qilamiz. Qurilma nomaʼlum boʻlsa, ehtiyot yuzasidan
    ishchining hamma seansi yopiladi.
    """
    if row.qurilma_id:
        RefreshToken.objects.filter(qurilma_id=row.qurilma_id).update(
            revoked=True, almashtirilgan=False
        )
        Qurilma.objects.filter(pk=row.qurilma_id).update(revoked=True, ishonchli=False)
    else:
        revoke_all(row.worker)


def revoke_zanjir(row: RefreshToken) -> None:
    """
    Butun seansni yopadi — shu zanjirdagi hamma token.

    `almashtirilgan=False` ataylab qoʻyiladi: bu token endi «rotatsiya
    tufayli eskirgan» emas, balki ataylab oʻchirilgan. Shu sababli unga
    ikki oynalik imtiyoz oraligʻi ham berilmaydi.
    """
    # `worker` ham shart sifatida qoʻshilgan — himoyaning ikkinchi qatlami.
    # Zanjir qandaydir sabab bilan takrorlanib qolsa ham, bir ishchining
    # chiqishi boshqasini tizimdan chiqarib yubormaydi.
    RefreshToken.objects.filter(zanjir=row.zanjir, worker=row.worker).update(
        revoked=True, almashtirilgan=False
    )


def revoke_refresh(token: str) -> None:
    """Chiqishda — shu token va u tegishli boʻlgan butun seans."""
    if not token:
        return
    row = RefreshToken.objects.filter(token_hash=_hash(token)).first()
    if row:
        revoke_zanjir(row)


def revoke_all(worker: Worker) -> None:
    """Ishchining barcha seanslarini bekor qilish (PIN tiklanganda)."""
    RefreshToken.objects.filter(worker=worker).update(revoked=True, almashtirilgan=False)


def tozalash() -> int:
    """Muddati oʻtgan tokenlarni oʻchirish. Xizmat buyrugʻi chaqiradi."""
    adet, _ = RefreshToken.objects.filter(expires_at__lt=timezone.now()).delete()
    return adet


# ---------------------------------------------------------------------
# Juftlikni yaratish
# ---------------------------------------------------------------------

def token_juftligi(
    worker: Worker, user_agent: str = "", qurilma: Qurilma | None = None
) -> dict[str, str]:
    return {
        "access": make_access(worker),
        "refresh": make_refresh(worker, user_agent, qurilma),
    }
