"""
=====================================================================
FaceID xizmati bilan aloqa.

Yuz tanish alohida servisda (face-service/app.py — InsightFace +
FastAPI) bajariladi. Django faqat unga murojaat qiladi va natijani
qoʻllaydi. Sabab: InsightFace modeli ogʻir (~350 MB) va uni asosiy
API jarayoniga qoʻshish butun tizimni sekinlashtiradi.

MUHIM — xizmat majburiy EMAS:
    FACE_SERVICE_URL boʻsh boʻlsa yoki servis javob bermasa, tizim
    yuz tanishni oʻchirib qoʻyadi va PIN bilan ishlashda davom etadi.
    Hech qachon xato bilan toʻxtamaydi — ishchi tizimdan tashqarida
    qolib ketmasligi kerak.

Tashqi kutubxona ishlatilmaydi (requests yoʻq) — faqat stdlib.
=====================================================================
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

log = logging.getLogger("tb")


class FaceXato(Exception):
    """Yuz aniqlanmadi / surat yaroqsiz — foydalanuvchiga koʻrsatiladi."""


def yoqilganmi() -> bool:
    """Yuz tanish sozlanganmi?"""
    return bool(getattr(settings, "FACE_SERVICE_URL", ""))


def _sorov(yol: str, tana: dict) -> dict:
    """
    Servisga POST yuboradi.

    Qaytadi: javob lugʻati.
    Koʻtaradi: FaceXato — surat yaroqsiz boʻlsa (422/400),
               RuntimeError — servis ishlamasa (chaqiruvchi PIN'ga oʻtadi).
    """
    manzil = settings.FACE_SERVICE_URL.rstrip("/") + yol
    xom = json.dumps(tana).encode("utf-8")

    sorov = urllib.request.Request(manzil, data=xom, method="POST")
    sorov.add_header("Content-Type", "application/json")
    if settings.FACE_SERVICE_TOKEN:
        sorov.add_header("X-Face-Token", settings.FACE_SERVICE_TOKEN)

    try:
        with urllib.request.urlopen(sorov, timeout=settings.FACE_TIMEOUT) as javob:
            return json.loads(javob.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        matn = ""
        try:
            matn = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            pass
        # 4xx — surat bilan bogʻliq muammo, foydalanuvchiga aytiladi
        if 400 <= e.code < 500:
            raise FaceXato(matn or "Suratda yuz aniqlanmadi") from e
        log.warning("Face servis xatosi (%s): %s", e.code, matn)
        raise RuntimeError("Face servis javob bermadi") from e
    except Exception as e:
        log.warning("Face servisga ulanib boʻlmadi: %s", e)
        raise RuntimeError("Face servisga ulanib boʻlmadi") from e


def vektor(surat: str) -> list[float]:
    """
    Suratdan 512 oʻlchovli vektor oladi.

    Koʻtaradi: FaceXato (yuz yoʻq) yoki RuntimeError (servis yoʻq).
    """
    if not yoqilganmi():
        raise RuntimeError("Face servis sozlanmagan")
    d = _sorov("/embed", {"image": surat})
    v = d.get("vector") or []
    if not v:
        raise FaceXato("Suratda yuz aniqlanmadi")
    return [float(x) for x in v]


def tekshir(kadrlar: list[str], nishon: list[float]) -> dict:
    """
    Bir nechta kadrni bazadagi vektor bilan solishtiradi.

    Bir nechta kadr jonlilik (liveness) uchun: kadrlar oʻzaro yaqin,
    lekin butunlay bir xil boʻlmasligi kerak — aks holda ekranga
    tutilgan surat boʻlishi mumkin.

    Qaytadi: {"mos": bool, "jonli": bool, "score": float, ...}
    """
    if not yoqilganmi():
        raise RuntimeError("Face servis sozlanmagan")
    if not nishon:
        raise RuntimeError("Ishchida saqlangan yuz vektori yoʻq")

    tana: dict = {"frames": kadrlar, "target": list(nishon)}
    if settings.FACE_THRESHOLD:
        tana["threshold"] = settings.FACE_THRESHOLD
    return _sorov("/verify", tana)
