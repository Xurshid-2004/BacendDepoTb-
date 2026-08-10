"""
=====================================================================
Holat, sogʻliq va QR tekshiruvi.

  GET /api/v1/state        — butun ilova holati (kirish talab qilinadi)
  GET /api/v1/bootstrap    — login sahifasi uchun minimal ochiq maʼlumot
  GET /api/v1/health       — servis holati (Docker healthcheck)
  GET /api/v1/verify/<id>  — QR imzo tekshiruvi (ochiq)
=====================================================================
"""

from __future__ import annotations

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from api.serializers import build_state
from core.models import Depo, Signature, Worker


@api_view(["GET"])
def state(request):
    """
    Butun ilova holati.

    MUHIM: bu endpoint kirishni talab qiladi. Ilgari (prototipda) holat
    ochiq edi va barcha ishchilar roʻyxati, hatto PIN hash'lari bilan,
    tizimga kirmagan har kimga berilardi. Endi bunday emas.
    """
    return Response({"data": build_state(request.user)})


@api_view(["GET"])
@permission_classes([AllowAny])
def bootstrap(request):
    """
    Login sahifasi uchun kerak boʻladigan eng kam maʼlumot: depo nomi.

    Ishchilar roʻyxati ATAYLAB berilmaydi — tabel raqami va PIN endi
    serverda tekshiriladi, mijozga roʻyxat kerak emas.
    """
    depo = Depo.joriy()
    return Response({
        "depo": {"kod": depo.kod, "nomi": depo.nomi, "tashkilot": depo.tashkilot},
        "ishchilarSoni": Worker.objects.filter(faol=True, deleted=False).count(),
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    """Docker/Caddy uchun — baza ulanishi ham tekshiriladi."""
    try:
        with connection.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
        baza = True
    except Exception:
        baza = False

    kod = 200 if baza else 503
    return Response({"ok": baza, "servis": "tb-django", "baza": baza}, status=kod)


@api_view(["GET"])
@permission_classes([AllowAny])
def verify(request, sig_id):
    """
    QR kod orqali imzoni tekshirish — hujjatdagi QR shu sahifaga olib keladi.
    Ochiq endpoint, lekin faqat imzo haqiqiyligini tasdiqlaydi.
    """
    s = Signature.objects.select_related("user").filter(id=sig_id).first()
    if not s:
        return Response({"ok": False, "error": "Imzo topilmadi"}, status=404)

    return Response({
        "ok": not s.bekor,
        "docType": s.doc_type,
        "docId": s.doc_id,
        "field": s.field,
        "sana": s.sana.isoformat(),
        "hash": s.hash,
        "bekor": s.bekor,
        "imzolagan": {
            "fio": s.user.fio if s.user else (s.payload or {}).get("fio", ""),
            "lavozim": (s.payload or {}).get("lavozim", ""),
        },
    })
