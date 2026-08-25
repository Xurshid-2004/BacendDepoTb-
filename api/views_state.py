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
from core import imzo
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

    # Butunlik: saqlangan hash payload bilan hali ham mosmi (bazaga
    # aralashib oʻzgartirilmaganmi). Faqat yangi HMAC imzolar uchun.
    butun = imzo.doc_ok(s)

    return Response({
        "ok": (not s.bekor) and butun,
        "docType": s.doc_type,
        "docId": s.doc_id,
        "field": s.field,
        "sana": s.sana.isoformat(),
        "hash": s.hash,
        "bekor": s.bekor,
        "butun": butun,
        "imzolagan": {
            "fio": s.user.fio if s.user else (s.payload or {}).get("fio", ""),
            "lavozim": (s.payload or {}).get("lavozim", ""),
        },
    })


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def verify_card(request):
    """
    ID-karta QR tekshiruvi — yagona imzo tizimining karta yoʻli.

    Ikki xil murojaat qabul qilinadi:
      • ?tabel=BLD0005016&imzo=0DE519A3D9FF807F   (ajratilgan)
      • ?payload=<QR ning butun matni>            (skanerdan kelgani)
      • POST {tabel, imzo} yoki {payload}

    Karta imzosi `Signature(doc_type="card_id")` da saqlanadi, xodimga
    `Worker.imzo_id` orqali bogʻlangan. Solishtirish doimiy vaqtda.
    """
    d = request.data if request.method == "POST" else request.query_params
    payload = (d.get("payload") or "").strip()
    tabel = (d.get("tabel") or "").strip()
    taqdim = (d.get("imzo") or "").strip()
    if payload and not (tabel and taqdim):
        p = imzo.parse_card_qr(payload)
        tabel = tabel or p["tabel"]
        taqdim = taqdim or p["imzo"]

    if not tabel:
        return Response({"ok": False, "error": "Tabel/ID aniqlanmadi"}, status=400)

    w = Worker.objects.filter(tabel=tabel, deleted=False).first()
    if not w:
        # Karta ID toʻliq (BLD…/Т6ЦЗ…) boʻlishi mumkin — bazadagi 4 xonali
        # tabelга keltirib qayta izlaymiz.
        t4 = imzo.tabel4(tabel)
        if t4:
            w = Worker.objects.filter(tabel=t4, deleted=False).first()
    if not w:
        return Response({"ok": False, "error": "Bunday tabel raqamli xodim yoʻq"}, status=404)

    sig = None
    if w.imzo_id:
        sig = Signature.objects.filter(id=w.imzo_id, doc_type="card_id").first()
    if sig is None:
        sig = (
            Signature.objects.filter(doc_type="card_id", doc_id=str(w.id))
            .order_by("-sana").first()
        )
    if not sig:
        return Response({"ok": False, "error": "Bu xodim uchun karta imzosi yoʻq"}, status=404)

    mos = (not sig.bekor) and imzo.card_verify(sig.hash, taqdim) if taqdim else False

    return Response({
        "ok": mos,
        "docType": "card_id",
        "tabel": w.tabel,
        "bekor": sig.bekor,
        "imzolagan": {
            "fio": w.fio,
            "lavozim": (sig.payload or {}).get("lavozim", "")
                       or (w.position.nomi if w.position else ""),
        },
    })
