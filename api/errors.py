"""
=====================================================================
Xatolarni frontend kutayotgan koʻrinishga keltirish.

Eski Next.js backend'i xatoni doim shunday qaytargan:
    { "error": "Xato matni" }

DRF esa {"detail": ...} yoki maydonlar lugʻatini qaytaradi. Shu
ishlovchi ikkalasini bitta shaklga keltiradi — frontend'dagi xato
koʻrsatish kodi oʻzgarmaydi.
=====================================================================
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

log = logging.getLogger("tb")


def _matn(data) -> str:
    """DRF xato tuzilmasidan oʻqiladigan bitta satr yasaydi."""
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "; ".join(_matn(x) for x in data if x)
    if isinstance(data, dict):
        if "detail" in data:
            return _matn(data["detail"])
        parts = []
        for key, val in data.items():
            parts.append(f"{key}: {_matn(val)}" if key != "non_field_errors" else _matn(val))
        return "; ".join(p for p in parts if p)
    return str(data)


def exception_handler(exc, context):
    # Django'ning oʻz xatolarini DRF tushunadigan holga keltiramiz
    if isinstance(exc, Http404):
        return Response({"error": "Topilmadi"}, status=status.HTTP_404_NOT_FOUND)

    if isinstance(exc, DjangoValidationError):
        return Response(
            {"error": "; ".join(exc.messages)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        log.warning("Bazada yaxlitlik xatosi: %s", exc)
        return Response(
            {"error": "Maʼlumot bazasi cheklovi buzildi (takrorlanuvchi qiymat boʻlishi mumkin)"},
            status=status.HTTP_409_CONFLICT,
        )

    javob = drf_handler(exc, context)

    if javob is None:
        # Kutilmagan xato — logga toʻliq yozamiz, mijozga qisqa xabar
        view = context.get("view").__class__.__name__ if context.get("view") else "?"
        log.exception("Kutilmagan xato (%s): %s", view, exc)
        return Response(
            {"error": "Serverda kutilmagan xato yuz berdi"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    javob.data = {"error": _matn(javob.data)}
    return javob
