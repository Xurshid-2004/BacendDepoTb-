"""
=====================================================================
Med-punkt — yakuniy xulosa SHU YERDA hisoblanadi.

Kiosk xom qiymat yuboradi, «meʼyorda / meʼyordan chetda» qarorini
faqat server qabul qiladi. Kioskdagi sozlamaga tegib xulosani
oʻzgartirib boʻlmaydi.

Ustuvorlik: xodimning shaxsiy meʼyori → umumiy chegaralar.
=====================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

from core.models import Worker
from medpunkt.models import IshchiMeyor, Sozlama


# ---------------------------------------------------------------------
# Kiritilgan qiymatlarni xavfsiz oʻqish
# ---------------------------------------------------------------------

def son(v, default=None) -> float | None:
    """Har qanday kelgan qiymatni floatga oʻgiradi; boʻlmasa `default`."""
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def butun(v, default=None) -> int | None:
    f = son(v, None)
    return int(round(f)) if f is not None else default


def uch_holat(v) -> bool | None:
    """
    Tasdiq belgisi uch holatli: True (tasdiqlandi), False (yoʻq),
    None (umuman tekshirilmagan). Panel uchunchisini kulrang koʻrsatadi.
    """
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("1", "true", "ha", "yes", "ok", "bor")


def vaqt_oqi(v) -> datetime:
    """
    ISO satr yoki UNIX sekundni aware datetime'ga oʻgiradi.
    Oʻqib boʻlmasa — hozirgi vaqt (oʻlchov yoʻqolib ketmasin).
    """
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=dt_timezone.utc)

    matn = str(v or "").strip()
    if matn:
        # "2026-09-13 11:06:47" va "…T11:06:47Z" — ikkalasi ham keladi
        tozalangan = matn.replace("Z", "+00:00").replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(tozalangan)
        except ValueError:
            dt = None
        if dt is not None:
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt

    return timezone.now()


# ---------------------------------------------------------------------
# Amaldagi chegaralar
# ---------------------------------------------------------------------

def chegaralar(worker: Worker | None, sozlama: Sozlama | None = None) -> dict:
    """
    Xodimga amalda qoʻllanadigan qon bosimi chegaralari.
    Shaxsiy meʼyor boʻlsa — oʻsha, boʻlmasa umumiy sozlama.
    """
    s = sozlama or Sozlama.joriy()
    natija = {
        "sisMax": s.qon_sis_max,
        "diaMax": s.qon_dia_max,
        "pulsMin": s.qon_puls_min,
        "pulsMax": s.qon_puls_max,
        "shaxsiy": False,
    }
    if worker is None:
        return natija

    m = IshchiMeyor.objects.filter(worker=worker, deleted=False).first()
    if m:
        natija.update(
            sisMax=m.sis_max, diaMax=m.dia_max,
            pulsMin=m.puls_min, pulsMax=m.puls_max, shaxsiy=True,
        )
    return natija


# ---------------------------------------------------------------------
# Xulosa
# ---------------------------------------------------------------------

def holat_hisobla(
    tur: str,
    qiymatlar: dict,
    worker: Worker | None,
    sozlama: Sozlama | None = None,
    tabel: str = "",
) -> tuple[str, str]:
    """
    `(holat, izoh)` qaytaradi.

      egasiz  — QR umuman skanerlanmagan (tabel yoʻq): oʻlchov kimniki
                ekani nomaʼlum, shuning uchun xulosa ham chiqarilmaydi;
      flagged — meʼyordan chetda;
      normal  — meʼyorda.

    Tabel bor, lekin bazada bunday xodim yoʻq boʻlsa — xulosa umumiy
    chegara boʻyicha baribir chiqariladi va izohga «xodim serverda
    yoʻq» qoʻshiladi. Bunday oʻlchov yoʻqolmaydi: xodim keyinroq
    bazaga qoʻshilsa, tabel boʻyicha bogʻlab olinadi.
    """
    if worker is None and not (tabel or "").strip():
        return "egasiz", "xodim aniqlanmagan (sessiyasiz oʻlchov)"

    s = sozlama or Sozlama.joriy()
    # Xodim topilmasa umumiy chegara qoʻllanadi — qiymat baribir baholanadi.
    qoshimcha = "" if worker is not None else "; xodim serverda yoʻq"

    if tur == "alko":
        mg = son(qiymatlar.get("mg_l"), 0.0) or 0.0
        aktiv = bool(qiymatlar.get("aktiv"))
        chegara = s.alko_chegara_mg_l if aktiv else s.alko_chegara_passiv_mg_l
        if mg > chegara:
            return "flagged", f"alko {mg:.3f} > {chegara:.3f} mg/l{qoshimcha}"
        return "normal", f"alko {mg:.3f} < {chegara:.3f} mg/l{qoshimcha}"

    if tur == "qon":
        ch = chegaralar(worker, s)
        qaysi = "shaxsiy" if ch["shaxsiy"] else "default"
        sis = butun(qiymatlar.get("sistolik"))
        dia = butun(qiymatlar.get("diastolik"))
        puls = butun(qiymatlar.get("puls"))

        if sis is None or dia is None:
            return "flagged", f"qon bosimi oʻqilmadi — qayta oʻlchash kerak{qoshimcha}"

        sabab: list[str] = []
        if sis > ch["sisMax"]:
            sabab.append(f"sistolik {sis} > {ch['sisMax']}")
        if dia > ch["diaMax"]:
            sabab.append(f"diastolik {dia} > {ch['diaMax']}")
        if puls is not None and puls < ch["pulsMin"]:
            sabab.append(f"puls {puls} < {ch['pulsMin']}")
        if puls is not None and puls > ch["pulsMax"]:
            sabab.append(f"puls {puls} > {ch['pulsMax']}")

        if sabab:
            return "flagged", f"{'; '.join(sabab)} ({qaysi} meʼyor){qoshimcha}"

        p = puls if puls is not None else "—"
        return "normal", f"{sis}/{dia} puls {p} — meʼyorda ({qaysi}){qoshimcha}"

    return "flagged", f"notanish oʻlchov turi: {tur}"


# ---------------------------------------------------------------------
# Xodimni tabel boʻyicha topish
# ---------------------------------------------------------------------

def worker_top(tabel: str) -> Worker | None:
    """
    Kiosk karta ID sini yuboradi (`BLD0000212`), bazada esa 4 xonali
    tabel turadi (`0212`). Avval toʻliq moslik, soʻng `imzo.tabel4`.
    """
    xom = (tabel or "").strip()
    if not xom:
        return None

    w = Worker.objects.filter(tabel=xom, deleted=False).first()
    if w:
        return w

    from core import imzo

    t4 = imzo.tabel4(xom)
    if not t4:
        return None
    return Worker.objects.filter(tabel=t4, deleted=False).first()
