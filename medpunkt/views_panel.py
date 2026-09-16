"""
=====================================================================
Panel endpointlari — JWT bilan (web sahifa `app/(sys)/medpunkt`).

  GET    /olchovlar                — oʻlchovlar (filtr bilan)
  GET    /hodisalar                — kiosk hodisalari
  POST   /hodisalar/<id>/korildi   — hodisani yopish
  GET    /meyorlar                 — shaxsiy meʼyorlar
  POST   /meyorlar                 — meʼyor kiritish / tahrirlash
  DELETE /meyorlar/<worker_id>     — meʼyorni olib tashlash
  GET    /sozlamalar               — umumiy chegaralar
  POST   /sozlamalar               — chegaralarni saqlash

Koʻrinish chegarasi SERVERDA qoʻyiladi:
  • `medpunkt.read.all` (yoki admin) — hamma oʻlchov;
  • mashinist yoʻriqchisi           — oʻz kolonnasi + oʻzi;
  • qolganlar                       — faqat oʻzi.
=====================================================================
"""

from __future__ import annotations

from datetime import date

from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.models import Kolonna, Worker
from core.permissions import worker_can
from medpunkt import logic
from medpunkt.models import Hodisa, IshchiMeyor, MedPunkt, Olchov, Sozlama
from medpunkt.serializers import (
    hodisa_json, meyor_json, olchov_json, punkt_json, sozlama_json,
)

# Bir soʻrovda qaytariladigan eng koʻp qator. `jami` esa haqiqiy sonni
# koʻrsatadi — sahifa «filtrni toraytiring» deb yozadi.
SAHIFA = 500

# Shifokor kiritadigan meʼyorlar uchun aqlga sigʻadigan oraliqlar.
CHEK = {
    "sis": (60, 250),
    "dia": (40, 150),
    "puls": (30, 220),
}


def xato(matn: str, kod: int = 400) -> Response:
    return Response({"error": matn}, status=kod)


def _hammasini_koradi(me: Worker) -> bool:
    return me.has_role("admin") or worker_can(me, "medpunkt.read.all")


def _korish_filtri(qs, me: Worker, worker_yoli: str = "worker"):
    """
    Foydalanuvchi koʻrishi mumkin boʻlgan yozuvlarga qisqartiradi.
    `medpunkt.read.all` boʻlsa hech narsa kesilmaydi.
    """
    if _hammasini_koradi(me):
        return qs

    from django.db.models import Q

    shart = Q(**{f"{worker_yoli}_id": me.id})

    # Mashinist yoʻriqchisi — oʻz kolonnasi ishchilari
    kolonnalar = list(
        Kolonna.objects.filter(instruktor=me, faol=True).values_list("id", flat=True)
    )
    if kolonnalar:
        shart |= Q(**{f"{worker_yoli}__kolonna_ref_id__in": kolonnalar})

    return qs.filter(shart)


def _sana(matn: str) -> date | None:
    try:
        return date.fromisoformat((matn or "").strip())
    except ValueError:
        return None


# =====================================================================
# GET /olchovlar
# =====================================================================

@api_view(["GET"])
def olchovlar(request):
    me = request.user
    if not worker_can(me, "medpunkt.read"):
        return xato("Med-punkt maʼlumotlarini koʻrish uchun ruxsatingiz yoʻq", 403)

    qs = (
        Olchov.objects.filter(deleted=False)
        .select_related("med_punkt", "worker", "worker__kolonna_ref")
    )
    qs = _korish_filtri(qs, me)

    q = request.query_params

    sana = _sana(q.get("sana", ""))
    if sana:
        qs = qs.filter(olchov_vaqti__date=sana)

    tur = (q.get("tur") or "").strip()
    if tur in ("alko", "qon"):
        qs = qs.filter(tur=tur)

    holat = (q.get("holat") or "").strip()
    if holat in ("normal", "flagged", "egasiz"):
        qs = qs.filter(holat=holat)

    punkt_kod = (q.get("medPunkt") or "").strip()
    if punkt_kod:
        qs = qs.filter(med_punkt__kod=punkt_kod)

    kolonna_id = (q.get("kolonnaId") or "").strip()
    if kolonna_id:
        qs = qs.filter(worker__kolonna_ref_id=kolonna_id)

    tabel = (q.get("tabel") or "").strip()
    if tabel:
        # Kioskdagi karta ID (BLD0000212) ham, bazadagi 4 xonali tabel ham
        # ishlasin — ikkalasi boʻyicha ham izlaymiz.
        from django.db.models import Q
        from core import imzo

        shart = Q(tabel__icontains=tabel) | Q(worker__tabel__icontains=tabel)
        t4 = imzo.tabel4(tabel)
        if t4:
            shart |= Q(worker__tabel=t4)
        qs = qs.filter(shart)

    jami = qs.count()
    qatorlar = [olchov_json(o) for o in qs.order_by("-olchov_vaqti")[:SAHIFA]]

    return Response({
        "olchovlar": qatorlar,
        "jami": jami,
        "punktlar": [punkt_json(p) for p in MedPunkt.objects.all()],
    })


# =====================================================================
# GET /hodisalar  ·  POST /hodisalar/<id>/korildi
# =====================================================================

@api_view(["GET"])
def hodisalar(request):
    me = request.user
    if not worker_can(me, "medpunkt.read"):
        return xato("Med-punkt maʼlumotlarini koʻrish uchun ruxsatingiz yoʻq", 403)

    qs = (
        Hodisa.objects.filter(deleted=False)
        .select_related("med_punkt", "worker", "worker__kolonna_ref")
    )
    qs = _korish_filtri(qs, me)

    q = request.query_params
    if (q.get("faqatYangi") or "").lower() in ("1", "true", "ha", "yes"):
        qs = qs.filter(korildi=False)

    punkt_kod = (q.get("medPunkt") or "").strip()
    if punkt_kod:
        qs = qs.filter(med_punkt__kod=punkt_kod)

    return Response({
        "hodisalar": [hodisa_json(h) for h in qs.order_by("-vaqt")[:SAHIFA]],
    })


@api_view(["POST"])
def hodisa_korildi(request, hodisa_id):
    me = request.user
    if not worker_can(me, "medpunkt.write"):
        return xato("Bu amal uchun ruxsatingiz yoʻq", 403)

    h = Hodisa.objects.filter(id=hodisa_id, deleted=False).first()
    if h is None:
        return xato("Hodisa topilmadi", 404)

    if not h.korildi:
        h.korildi = True
        h.save(update_fields=["korildi"])

    return Response({"ok": True, "id": str(h.id), "korildi": True})


# =====================================================================
# GET/POST /meyorlar  ·  DELETE /meyorlar/<worker_id>
# =====================================================================

def _oraliq(nom: str, qiymat, past: int, yuqori: int) -> int:
    son = logic.butun(qiymat)
    if son is None:
        raise ValueError(f"{nom} — raqam kiritilmadi")
    if not (past <= son <= yuqori):
        raise ValueError(f"{nom} {past}–{yuqori} oraligʻida boʻlishi kerak")
    return son


@api_view(["GET", "POST"])
def meyorlar(request):
    me = request.user

    if request.method == "GET":
        if not (worker_can(me, "medpunkt.read.all") or worker_can(me, "medpunkt.write")):
            return xato("Meʼyorlarni koʻrish uchun ruxsatingiz yoʻq", 403)
        qs = (
            IshchiMeyor.objects.filter(deleted=False)
            .select_related("worker")
            .order_by("worker__familiya", "worker__ism")
        )
        return Response({"meyorlar": [meyor_json(m) for m in qs]})

    # --- POST: kiritish / tahrirlash ---
    if not worker_can(me, "medpunkt.write"):
        return xato("Meʼyor kiritish uchun ruxsatingiz yoʻq", 403)

    d = request.data if isinstance(request.data, dict) else {}

    worker_id = str(d.get("workerId") or "").strip()
    tabel = str(d.get("tabel") or "").strip()

    if worker_id:
        w = Worker.objects.filter(id=worker_id, deleted=False).first()
    elif tabel:
        w = logic.worker_top(tabel)
    else:
        return xato("Xodim koʻrsatilmadi — tabel raqamini kiriting")

    if w is None:
        return xato("Bunday tabel raqamli xodim topilmadi", 404)

    try:
        sis = _oraliq("Sistolik", d.get("sisMax"), *CHEK["sis"])
        dia = _oraliq("Diastolik", d.get("diaMax"), *CHEK["dia"])
        puls_min = _oraliq("Puls minimum", d.get("pulsMin"), *CHEK["puls"])
        puls_max = _oraliq("Puls maksimum", d.get("pulsMax"), *CHEK["puls"])
    except ValueError as e:
        return xato(str(e))

    if dia >= sis:
        return xato("Diastolik sistolikdan kichik boʻlishi kerak")
    if puls_min >= puls_max:
        return xato("Puls minimumi maksimumdan kichik boʻlishi kerak")

    m, _ = IshchiMeyor.objects.update_or_create(
        worker=w,
        defaults={
            "sis_max": sis,
            "dia_max": dia,
            "puls_min": puls_min,
            "puls_max": puls_max,
            "izoh": str(d.get("izoh") or "").strip()[:255],
            "shifokor": me.fio[:128],
            "deleted": False,
        },
    )
    m.refresh_from_db()
    return Response({"ok": True, "meyor": meyor_json(m)})


@api_view(["DELETE"])
def meyor_ochir(request, worker_id):
    me = request.user
    if not worker_can(me, "medpunkt.write"):
        return xato("Bu amal uchun ruxsatingiz yoʻq", 403)

    m = IshchiMeyor.objects.filter(worker_id=worker_id, deleted=False).first()
    if m is None:
        return xato("Meʼyor topilmadi", 404)

    # Yumshoq oʻchirish — kim qachon qoʻygani tarixda qoladi.
    m.deleted = True
    m.save(update_fields=["deleted", "yangilandi"])

    return Response({"ok": True, "workerId": str(worker_id)})


# =====================================================================
# GET/POST /sozlamalar
# =====================================================================

MAYDON = {
    "alkoChegaraMgL": ("alko_chegara_mg_l", "float", 0.0, 2.0),
    "alkoChegaraPassivMgL": ("alko_chegara_passiv_mg_l", "float", 0.0, 2.0),
    "qonSisMax": ("qon_sis_max", "int", *CHEK["sis"]),
    "qonDiaMax": ("qon_dia_max", "int", *CHEK["dia"]),
    "qonPulsMin": ("qon_puls_min", "int", *CHEK["puls"]),
    "qonPulsMax": ("qon_puls_max", "int", *CHEK["puls"]),
    "limit12Soat": ("limit_12_soat", "int", 1, 50),
    "arxivKun": ("arxiv_kun", "int", 1, 3650),
}


@api_view(["GET", "POST"])
def sozlamalar(request):
    me = request.user
    s = Sozlama.joriy()

    if request.method == "GET":
        if not (worker_can(me, "medpunkt.read.all") or worker_can(me, "medpunkt.write")):
            return xato("Chegaralarni koʻrish uchun ruxsatingiz yoʻq", 403)
        return Response({"sozlamalar": sozlama_json(s)})

    if not worker_can(me, "medpunkt.write"):
        return xato("Chegaralarni oʻzgartirish uchun ruxsatingiz yoʻq", 403)

    d = request.data if isinstance(request.data, dict) else {}
    ozgardi: list[str] = []

    for kalit, (maydon, tip, past, yuqori) in MAYDON.items():
        if kalit not in d:
            continue
        qiymat = logic.son(d[kalit]) if tip == "float" else logic.butun(d[kalit])
        if qiymat is None:
            return xato(f"{kalit} — raqam kiritilmadi")
        if not (past <= qiymat <= yuqori):
            return xato(f"{kalit} {past}–{yuqori} oraligʻida boʻlishi kerak")
        setattr(s, maydon, qiymat)
        ozgardi.append(maydon)

    if s.qon_puls_min >= s.qon_puls_max:
        return xato("Puls minimumi maksimumdan kichik boʻlishi kerak")
    if s.qon_dia_max >= s.qon_sis_max:
        return xato("Diastolik maksimumi sistolikdan kichik boʻlishi kerak")

    if ozgardi:
        s.save(update_fields=[*ozgardi, "yangilandi"])

    s.refresh_from_db()
    return Response({"ok": True, "sozlamalar": sozlama_json(s)})
