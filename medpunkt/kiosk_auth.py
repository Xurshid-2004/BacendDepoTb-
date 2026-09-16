"""
=====================================================================
Kiosk autentifikatsiyasi — `X-API-Key` sarlavhasi.

Kiosk brauzer emas, foydalanuvchi ham emas — unda JWT yoʻq. U oʻzini
bitta uzun kalit bilan tanishtiradi (`MEDPUNKT_API_KEY`, .env dan).

Qoida: kalit sozlanmagan boʻlsa endpoint OCHILMAYDI (503). Yaʼni
`.env` unutilsa tizim ochiq qolib ketmaydi, aksincha — yopiladi.
=====================================================================
"""

from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.response import Response


def kalit_tekshir(request) -> Response | None:
    """
    Xato boʻlsa tayyor javob, hammasi joyida boʻlsa None qaytaradi.

      503 — serverda kalit sozlanmagan;
      401 — kalit notoʻgʻri yoki berilmagan.

    Solishtirish doimiy vaqtda (`hmac.compare_digest`) — javob
    tezligiga qarab kalitni taxmin qilib boʻlmaydi.
    """
    kutilgan = (getattr(settings, "MEDPUNKT_API_KEY", "") or "").strip()
    if not kutilgan:
        return Response(
            {"error": "Med-punkt kaliti serverda sozlanmagan (MEDPUNKT_API_KEY)"},
            status=503,
        )

    kelgan = (
        request.headers.get("X-API-Key")
        or request.headers.get("X-Api-Key")
        or ""
    ).strip()
    if not kelgan or not hmac.compare_digest(kelgan, kutilgan):
        return Response({"error": "Kalit mos emas"}, status=401)

    return None
