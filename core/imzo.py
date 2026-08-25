"""
=====================================================================
YAGONA IMZO TIZIMI — bitta kripto yadro, bitta QR, bitta verify.

Tizimda ikki xil imzo ISHTIROK etadi, lekin MEXANIZMI bitta (HMAC-SHA256):

  1) Hujjat imzosi  (doc_type: journal / requisition / card / kip)
     — kim, qaysi hujjatning qaysi maydonini, qachon tasdiqlagani.
     `doc_hmac(...)` bilan hisoblanadi, `Signature.hash` ga yoziladi.
     QR ichida `/verify/<sig_id>` havolasi boradi.

  2) Xodim ID-kartasi imzosi  (doc_type: "card_id")
     — kartaning haqiqiyligi (bu karta shu tabel raqamiga tegishli).
     Mavjud (depo-id da chop etilgan) kartalar `import_imzolar` orqali
     import qilinadi — qiymati depo-id niki (IMZO_HMAC16) boʻlicha saqlanadi.
     Yangi kartalar `card_hmac(...)` bilan chiqariladi.

MUHIM: hujjatni tekshirish `sig_id` (UUID) boʻyicha qidirish orqali
bajariladi — hash qayta hisoblanmaydi. Shu sabab hash algoritmini
FNV dan HMAC ga koʻtarish eski imzolarni buzmaydi (ular ham id boʻyicha
topiladi). HMAC esa hashni SOXTALASHTIRIB boʻlmaydigan qiladi: kalitsiz
hech kim (id, payload) ga mos hash yasay olmaydi.
=====================================================================
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings


# ---------------------------------------------------------------------
# Tabel raqamini moslashtirish
# ---------------------------------------------------------------------

def tabel4(raw: str) -> str:
    """
    Karta ID sini (masalan `BLD0002051`, `Т6ЦЗ-00003`) bazadagi 4 xonali
    `tabel` ga keltiradi — raqamlarning oxirgi 4 tasi, 4 xonagacha nol bilan.

    DIQQAT: bu «oxirgi 4 raqam» qoidasi kolliziyaga moyil
    (`BLD0000003` va `Т6ЦЗ-00003` — ikkalasi `0003`). Shu sabab import
    va verify FIO ni ham solishtiradi (core/management/commands/import_imzolar,
    kerak boʻlsa kelgusida verify).
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits[-4:].zfill(4) if digits else ""


# ---------------------------------------------------------------------
# Kalitlar (.env dan)
# ---------------------------------------------------------------------

def _doc_key() -> bytes:
    """Hujjat imzolari uchun maxfiy kalit. Alohida boʻlmasa — JWT_SECRET."""
    raw = getattr(settings, "IMZO_SECRET_KEY", "") or getattr(settings, "JWT_SECRET", "")
    return raw.encode("utf-8")


def _card_key() -> bytes:
    """
    ID-karta imzolari uchun kalit. depo-id bilan bitta boʻlishi shart —
    shunda depo-id da chiqarilgan kartalar bilan Tb Main chiqargan
    kartalar bitta oilaga tushadi (32 baytli hex kalit).
    """
    raw = getattr(settings, "CARD_HMAC_KEY", "")
    if not raw:
        return b""
    # depo-id kaliti 64 belgili hex — baytga aylantiramiz. Hex boʻlmasa
    # matnning oʻzini bayt sifatida olamiz (moslashuvchan).
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


# ---------------------------------------------------------------------
# Hujjat imzosi
# ---------------------------------------------------------------------

def doc_hmac(doc_type: str, doc_id, field: str, user_id, sana_iso: str) -> str:
    """
    Hujjat imzosining qatʼiy izi. HMAC-SHA256, hex (64 belgi).
    Kirish qatʼiy tartibda birlashtiriladi — hujjatlar orasida bir xil
    natija chiqmasligi uchun har bir boʻlak `\\x1f` bilan ajratiladi.
    """
    parts = [doc_type, str(doc_id), field or "", str(user_id or ""), sana_iso or ""]
    msg = "\x1f".join(parts).encode("utf-8")
    return hmac.new(_doc_key(), msg, hashlib.sha256).hexdigest()


def doc_ok(sig) -> bool:
    """
    Saqlangan `Signature.hash` payload bilan hali ham mos keladimi —
    bazaga aralashib hash yoki payload oʻzgartirilmaganini bildiradi.
    Faqat HMAC (64 hex) formatidagi yangi imzolar uchun tekshiriladi;
    eski (FNV, 16 hex) imzolar uchun True (buzilmaslik uchun).
    """
    h = sig.hash or ""
    if len(h) != 64:  # eski format — tekshirmaymiz
        return not sig.bekor
    p = sig.payload or {}
    calc = doc_hmac(sig.doc_type, sig.doc_id, sig.field, sig.user_id, p.get("sana", ""))
    return (not sig.bekor) and hmac.compare_digest(calc, h)


# ---------------------------------------------------------------------
# ID-karta imzosi
# ---------------------------------------------------------------------

def card_signable(depo: str, fio: str, lavozim: str, tabel: str) -> str:
    """
    Karta QR ichidagi matn (IMZO qatoridan tashqari). Yangi kartalar
    shu format boʻyicha chiqariladi — depo-id koʻrinishiga mos.
    """
    return (
        f"{depo} {fio} ning elektron imzosi.\n"
        f"Lavozimi: {lavozim}\n"
        f"ID: {tabel}"
    )


def card_hmac(depo: str, fio: str, lavozim: str, tabel: str) -> str:
    """Yangi ID-karta imzosi — HMAC-SHA256, 16 belgi hex (katta harf)."""
    msg = card_signable(depo, fio, lavozim, tabel).encode("utf-8")
    return hmac.new(_card_key(), msg, hashlib.sha256).hexdigest()[:16].upper()


def card_verify(stored: str, taqdim: str) -> bool:
    """Skanerdan kelgan imzo saqlangani bilan mos keladimi (doimiy vaqtda)."""
    if not stored or not taqdim:
        return False
    return hmac.compare_digest(stored.strip().upper(), taqdim.strip().upper())


def parse_card_qr(text: str) -> dict:
    """
    depo-id karta QR matnidan `tabel` va `imzo` ni ajratib oladi.
    Namuna:
        Buxoro lokomotiv deposida FIO ning elektron imzosi.
        Lavozimi: ...
        ID: BLD0005016
        IMZO: 0DE519A3D9FF807F
    """
    tabel = imzo = ""
    for line in (text or "").splitlines():
        s = line.strip()
        up = s.upper()
        if up.startswith("ID:"):
            tabel = s.split(":", 1)[1].strip()
        elif up.startswith("IMZO:"):
            imzo = s.split(":", 1)[1].strip()
    # Ba'zi skanerlar bitta qatorga qo'shib yuboradi — zaxira ajratish:
    if not tabel and "ID:" in (text or ""):
        tabel = text.split("ID:", 1)[1].split()[0].strip()
    if not imzo and "IMZO:" in (text or ""):
        imzo = text.split("IMZO:", 1)[1].split()[0].strip()
    return {"tabel": tabel, "imzo": imzo}
