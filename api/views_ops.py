"""
=====================================================================
Amallar (mutatsiyalar) — ilgari lib/store.tsx ichida brauzerda
bajarilgan har bir amal endi shu yerda, serverda bajariladi.

Har bir endpoint:
  1. ruxsatni SERVERDA tekshiradi (frontend tugmani yashirgani yetarli emas);
  2. biznes-qoidani qoʻllaydi (holat oʻtishi, ombor qoldigʻi, imzo);
  3. audit yozuvini qoldiradi;
  4. YANGILANGAN TOʻLIQ HOLATNI qaytaradi.

4-band ataylab: mijozda hech qachon chala/eskirgan maʼlumot qolmaydi.
Har amaldan keyin frontend serverdan kelgan haqiqatni oladi.
=====================================================================
"""

from __future__ import annotations

import logging
import uuid

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.serializers import build_state
from core import logic
from core.models import (
    AccessOverride, AuditLog, Card, CardIssue, Depo, Exam, Incident, Item,
    JournalEntry, Kip, Line, Norm, Notification, Position, Request,
    RequestLine, Signature, Stock, StockMove, Talon, TalonHistory, Unit, Worker,
)
from core.permissions import worker_can

log = logging.getLogger("tb")


# ---------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------

def xato(matn: str, kod: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": matn}, status=kod)


def holat(me: Worker | None = None) -> Response:
    """Amaldan keyin yangilangan toʻliq holatni qaytaradi."""
    return Response({"ok": True, "state": build_state(me)})


def tekshir(request, perm: str) -> str | None:
    """Ruxsat boʻlmasa xato matnini qaytaradi, boʻlsa None."""
    if not worker_can(request.user, perm):
        return "Bu amal uchun ruxsatingiz yoʻq"
    return None


def uuid_yoki_none(qiymat) -> uuid.UUID | None:
    """
    Kelgan id'ni UUID'ga oʻgiradi, boʻlmasa None.

    Frontend yangi yozuv uchun vaqtinchalik id yasashi mumkin
    ("w1754745600000"). Uni toʻgʻridan-toʻgʻri UUIDField'ga filter
    qilish ValidationError beradi — shuning uchun bunday id yangi
    yozuv sifatida qabul qilinadi.
    """
    matn = str(qiymat or "").strip()
    if not matn:
        return None
    try:
        return uuid.UUID(matn)
    except (ValueError, AttributeError, TypeError):
        return None


def audit(me: Worker | None, obyekt: str, amal: str, izoh: str = "") -> None:
    AuditLog.objects.create(user=me, obyekt=obyekt, amal=amal, izoh=izoh or "")


def notify(worker_id, sarlavha: str, matn: str, turi: str = "info") -> None:
    Notification.objects.create(
        worker_id=worker_id, turi=turi, sarlavha=sarlavha, matn=matn
    )


def imzo_yarat(me: Worker | None, doc_type: str, doc_id: str, field: str) -> Signature:
    """Hujjatga imzo qoʻyadi — QR orqali tekshirish uchun hash saqlanadi."""
    payload = {}
    if me:
        payload = {
            "fio": me.fio,
            "lavozim": me.position.nomi if me.position else "",
            "sana": timezone.now().isoformat(),
        }
    return Signature.objects.create(
        doc_type=doc_type,
        doc_id=str(doc_id),
        field=field,
        user=me,
        hash=logic.make_hash(f"{doc_type}{doc_id}{field}{me.id if me else ''}{timezone.now().timestamp()}"),
        payload=payload,
    )


def son(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# =====================================================================
# ARIZALAR
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def request_create(request):
    """
    Yangi ariza. Frontend: createRequest(workerId, itemIds, turi)

    Serverda har bir buyum uchun can_request() qoidasi tekshiriladi —
    muddati kelmagan yoki mavsumi yopiq buyumga ariza oʻtmaydi.
    """
    if (e := tekshir(request, "request.create")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    worker_id = request.data.get("workerId") or str(me.id)
    item_ids = request.data.get("itemIds") or []
    turi = request.data.get("turi", "oddiy")

    if not item_ids:
        return xato("Kamida bitta buyum tanlanishi kerak")

    worker = Worker.objects.filter(id=worker_id, deleted=False, faol=True).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    # Boshqa ishchi nomidan ariza — faqat TB xodimi yoki admin
    if str(worker.id) != str(me.id) and not me.has_role("tb_xodim"):
        return xato("Boshqa ishchi nomidan ariza yuborish huquqingiz yoʻq", status.HTTP_403_FORBIDDEN)

    # Har bir buyumni qoidaga solishtiramiz
    for iid in item_ids:
        mumkin, sabab = logic.can_request(worker, iid)
        if not mumkin:
            nomi = Item.objects.filter(id=iid).values_list("nomi", flat=True).first() or "Buyum"
            return xato(f"{nomi}: {sabab}")

    depo = Depo.joriy()
    req = Request.objects.create(
        raqam=logic.next_req_no(depo),
        worker=worker,
        turi=turi,
        status="SUBMITTED",
        yaratgan=me,
        yaratilgan=logic.today(),
    )

    for iid in item_ids:
        item = Item.objects.filter(id=iid).first()
        if item:
            RequestLine.objects.create(
                request=req, item=item, soni=1, unit=item.unit, narx=item.narx
            )

    req.transitions.create(from_status="DRAFT", to_status="SUBMITTED", user=me)

    audit(me, f"ariza {req.raqam}", "yaratildi")
    notify(worker.id, "Ariza yuborildi", f"{req.raqam} — bugalteriya koʻrigida")

    return holat(me)


@api_view(["PATCH"])
@transaction.atomic
def request_update(request, req_id):
    """Bugalter qatorlarni va blanka maydonlarini toʻldiradi."""
    if (e := tekshir(request, "request.approve1")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    req = Request.objects.filter(id=req_id).first()
    if not req:
        return xato("Ariza topilmadi", status.HTTP_404_NOT_FOUND)

    if req.status in ("COMPLETED", "REJECTED"):
        return xato("Yakunlangan yoki rad etilgan arizani tahrirlab boʻlmaydi")

    lines = request.data.get("lines")
    if isinstance(lines, list):
        req.lines.all().delete()
        for l in lines:
            item = Item.objects.filter(id=l.get("itemId")).first()
            if not item:
                continue
            RequestLine.objects.create(
                request=req,
                item=item,
                soni=son(l.get("soni"), 1),
                unit=l.get("unit") or item.unit,
                narx=son(l.get("narx"), float(item.narx)),
            )

    bug = request.data.get("bugField")
    if isinstance(bug, dict):
        req.bug_field = {**(req.bug_field or {}), **bug}
        req.save(update_fields=["bug_field"])

    audit(me, f"ariza {req.raqam}", "bugalter maʼlumot toʻldirdi / tahrirladi")
    return holat(me)


@api_view(["POST"])
@transaction.atomic
def request_advance(request, req_id):
    """
    Arizani keyingi bosqichga oʻtkazish.

    COMPLETED boʻlganda: ombordan chiqim yoziladi va buyumlar ishchining
    MB-6 kartochkasiga qayd etiladi (ilgari brauzerda qilinardi).
    """
    me = request.user
    req = (
        Request.objects.select_for_update()
        .filter(id=req_id)
        .prefetch_related("lines")
        .first()
    )
    if not req:
        return xato("Ariza topilmadi", status.HTTP_404_NOT_FOUND)

    mumkin, sabab = logic.can_advance(me, req)
    if not mumkin:
        return xato(sabab, status.HTTP_403_FORBIDDEN)

    izoh = str(request.data.get("izoh", "") or "")
    oldingi = req.status
    keyingi = logic.next_status(oldingi)

    # Blankaning tegishli maydoni imzolanadi
    field = logic.SIGN_FIELD.get(oldingi)
    if field:
        imzo_yarat(me, "requisition", req.id, field)

    req.transitions.create(
        from_status=oldingi, to_status=keyingi, user=me, izoh=izoh
    )
    req.status = keyingi

    if keyingi == "COMPLETED":
        req.yakunlangan = logic.today()
        card, _ = Card.objects.get_or_create(
            worker=req.worker, defaults={"ochilgan": logic.today()}
        )

        for l in req.lines.all():
            # Ombor qoldigʻi — manfiyga tushmaydi
            stock, _ = Stock.objects.get_or_create(item=l.item, defaults={"qoldiq": 0})
            yangi = max(0, float(stock.qoldiq) - float(l.soni))
            stock.qoldiq = yangi
            stock.save(update_fields=["qoldiq"])

            StockMove.objects.create(
                item=l.item,
                turi="chiqim",
                soni=l.soni,
                sana=logic.today(),
                izoh=f"Ariza {req.raqam}",
                hujjat_id=str(req.id),
            )

            imzo = imzo_yarat(me, "card", card.id, "25")
            CardIssue.objects.create(
                card=card,
                item=l.item,
                sana=logic.today(),
                soni=l.soni,
                yaroqlilik=100,
                imzo_id=str(imzo.id),
            )

        notify(req.worker_id, "Ariza yakunlandi",
               f"{req.raqam} — buyumlar kartochkangizga qayd etildi")
    else:
        notify(req.worker_id, "Ariza holati oʻzgardi",
               f"{req.raqam} — keyingi bosqichga oʻtdi")

    req.save(update_fields=["status", "yakunlangan"])
    audit(me, f"ariza {req.raqam}", f"holat → {keyingi}", izoh)

    return holat(me)


@api_view(["POST"])
@transaction.atomic
def request_reject(request, req_id):
    """Arizani rad etish. Depo boshligʻidan tashqari hammaga sabab majburiy."""
    me = request.user
    req = Request.objects.select_for_update().filter(id=req_id).first()
    if not req:
        return xato("Ariza topilmadi", status.HTTP_404_NOT_FOUND)

    if req.status in ("COMPLETED", "REJECTED"):
        return xato("Ariza allaqachon yakunlangan yoki rad etilgan")

    # Rad etish huquqi — shu bosqichda harakat qila oladigan roldagina
    kerak = logic.ACTOR_ROLE.get(req.status)
    if kerak and not me.has_role(kerak):
        return xato("Bu bosqichda arizani rad etish huquqingiz yoʻq", status.HTTP_403_FORBIDDEN)

    izoh = str(request.data.get("izoh", "") or "").strip()
    if logic.reject_reason_required(me.roles or []) and not izoh:
        return xato("Rad etish sababini koʻrsating")

    req.transitions.create(
        from_status=req.status, to_status="REJECTED", user=me, izoh=izoh
    )
    req.status = "REJECTED"
    req.save(update_fields=["status"])

    notify(
        req.worker_id,
        "Ariza rad etildi",
        f"{req.raqam} — {me.fio} tomonidan. Sabab: {izoh or 'koʻrsatilmagan'}",
        turi="reject",
    )
    audit(me, f"ariza {req.raqam}", "rad etildi", izoh)

    return holat(me)


# =====================================================================
# TB JURNALI
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def journal_add(request):
    if (e := tekshir(request, "journal.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    d = request.data

    # --- bosqich: faqat 1 yoki 2. Notoʻgʻri qiymat jimgina 1-ga
    #     aylantirilmaydi — yozuv notoʻgʻri kitobga tushib ketmasligi kerak.
    try:
        bosqich = int(d.get("bosqich"))
    except (TypeError, ValueError):
        return xato("Bosqich koʻrsatilmadi (1 yoki 2 boʻlishi kerak)")
    if bosqich not in (1, 2):
        return xato("Bosqich faqat 1 yoki 2 boʻlishi mumkin")

    nomuvofiqlik = str(d.get("nomuvofiqlik", "")).strip()
    if not nomuvofiqlik:
        return xato("Nomuvofiqlik matni kiritilmadi")
    if not d.get("muddat"):
        return xato("Bajarish muddati koʻrsatilishi shart")

    # Sana kelmasa — serverning bugungi sanasi. 1-ustun hech qachon boʻsh
    # qolmaydi, mijoz soatiga ham bogʻliq boʻlmaydi.
    sana = d.get("sana") or timezone.localdate().isoformat()

    # Komissiya boʻsh kelsa — 2-ustunga yozuvni kiritayotgan xodim yoziladi.
    komissiya = d.get("komissiya") or []
    if not isinstance(komissiya, list) or not komissiya:
        komissiya = [{
            "fio": f"{me.familiya} {me.ism} {me.otasi}".strip(),
            "lavozim": (me.position.nomi if me.position else "TB muhandisi"),
        }]

    j = JournalEntry.objects.create(
        bosqich=bosqich,
        sana=sana,
        komissiya=komissiya,
        nomuvofiqlik=nomuvofiqlik,
        chora=str(d.get("chora", "")),
        masul=str(d.get("masul", "")),
        masul_lavozim=str(d.get("masulLavozim", "")),
        muddat=d["muddat"],
        bajarildi=bool(d.get("bajarildi")),
        bajarilgan_izoh=str(d.get("bajarilganIzoh", "") or ""),
    )
    audit(me, f"jurnal {j.bosqich}-bosqich", "yozuv qoʻshildi", nomuvofiqlik[:80])
    return holat(me)


@api_view(["POST"])
@transaction.atomic
def journal_sign(request, entry_id):
    """
    7-ustun — chora-tadbir bajarilganini TASDIQLASH.

    Tasdiqlangach yozuv «bajarildi» deb belgilanadi va QR imzo qoʻyiladi.
    Imzo hujjatdagi qatʼiy iz: kim, qaysi lavozimda va qachon tasdiqlagani
    imzo payload'ida oʻsha paytdagi holicha saqlanadi.
    """
    if (e := tekshir(request, "journal.sign")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    # select_for_update — bir vaqtda ikki kishi tasdiqlab yuborsa,
    # ikkinchisi birinchisini kutadi va «allaqachon tasdiqlangan» javobini oladi.
    j = JournalEntry.objects.select_for_update().filter(id=entry_id).first()
    if not j:
        return xato("Jurnal yozuvi topilmadi", status.HTTP_404_NOT_FOUND)

    if j.bajarildi and j.imzo_id:
        return xato("Bu yozuv allaqachon tasdiqlangan", status.HTTP_409_CONFLICT)

    j.bajarildi = True
    j.bajarilgan_izoh = str(request.data.get("izoh", "") or "").strip() or "Bajarildi"
    j.imzo = imzo_yarat(me, "journal", j.id, "07")
    j.save(update_fields=["bajarildi", "bajarilgan_izoh", "imzo"])

    audit(me, f"jurnal yozuvi {j.id}", "bajarildi deb tasdiqlandi", j.nomuvofiqlik[:80])
    return holat(me)


# =====================================================================
# OMBORXONA
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def stock_in(request):
    if (e := tekshir(request, "stock.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    item = Item.objects.filter(id=request.data.get("itemId")).first()
    if not item:
        return xato("Buyum topilmadi", status.HTTP_404_NOT_FOUND)

    soni = son(request.data.get("soni"))
    if soni <= 0:
        return xato("Miqdor 0 dan katta boʻlishi kerak")

    izoh = str(request.data.get("izoh", "") or "")

    stock, _ = Stock.objects.get_or_create(item=item, defaults={"qoldiq": 0})
    Stock.objects.filter(pk=stock.pk).update(qoldiq=F("qoldiq") + soni)

    StockMove.objects.create(
        item=item, turi="kirim", soni=soni, sana=logic.today(), izoh=izoh
    )
    audit(me, f"ombor {item.nomi}", f"kirim +{soni:g}", izoh)
    return holat(me)


# =====================================================================
# TALON / IMTIXON / KIP
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def talon_toggle(request):
    if (e := tekshir(request, "talon.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    worker_id = request.data.get("workerId")
    raqam = int(request.data.get("raqam") or 0)
    sabab = str(request.data.get("sabab", "") or "")

    if raqam not in (1, 2, 3):
        return xato("Talon raqami 1, 2 yoki 3 boʻlishi kerak")

    talon = Talon.objects.select_for_update().filter(worker_id=worker_id, raqam=raqam).first()
    if not talon:
        return xato("Talon topilmadi", status.HTTP_404_NOT_FOUND)

    amal = "qaytarildi" if talon.olingan else "olindi"
    talon.olingan = not talon.olingan
    talon.save(update_fields=["olingan"])

    TalonHistory.objects.create(talon=talon, amal=amal, tb_xodim=me, sabab=sabab)

    notify(
        worker_id,
        "Talon olindi" if amal == "olindi" else "Talon qaytarildi",
        f"{raqam}-sonli talon {amal}" + (f". Sabab: {sabab}" if sabab else ""),
    )
    audit(me, f"talon {raqam} / {worker_id}", amal, sabab)
    return holat(me)


@api_view(["POST"])
@transaction.atomic
def kip_add(request):
    if (e := tekshir(request, "kip.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    d = request.data

    worker = Worker.objects.filter(id=d.get("workerId"), deleted=False).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)
    if not d.get("sana"):
        return xato("Sana koʻrsatilmadi")

    muddat_oy = int(d.get("muddatOy") or 1)
    sana = d["sana"]
    tugash = logic.add_months(
        timezone.datetime.fromisoformat(str(sana)).date()
        if isinstance(sana, str) else sana,
        muddat_oy,
    )

    kip = Kip.objects.create(
        worker=worker,
        yoriqchi_id=d.get("yoriqchiId") or me.id,
        liniya=str(d.get("liniya", "")),
        sana=sana,
        muddat_oy=muddat_oy,
        tugash=tugash,
    )
    imzo = imzo_yarat(me, "kip", kip.id, "04")
    kip.imzo_id = str(imzo.id)
    kip.save(update_fields=["imzo_id"])

    notify(worker.id, "Yangi KIP",
           f"{kip.liniya} · {muddat_oy} oy · tugash: {tugash.isoformat()}")
    audit(me, f"KIP {kip.id}", "yozildi")
    return holat(me)


@api_view(["POST"])
@transaction.atomic
def exam_set(request):
    if (e := tekshir(request, "exam.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    worker = Worker.objects.filter(id=request.data.get("workerId"), deleted=False).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    sana = request.data.get("sana")
    if not sana:
        return xato("Imtixon sanasi koʻrsatilmadi")
    davriylik = int(request.data.get("davriylikOy") or 12)

    Exam.objects.update_or_create(
        worker=worker,
        defaults={"oxirgi": sana, "davriylik_oy": davriylik, "natija": "otdi"},
    )

    keyingi = logic.add_months(
        timezone.datetime.fromisoformat(str(sana)).date(), davriylik
    )
    notify(worker.id, "TB imtixoni", f"Keyingi imtixon: {keyingi.isoformat()}")
    audit(me, f"imtixon {worker.tabel}", "yangilandi")
    return holat(me)


# =====================================================================
# BUYUM / NORMA
# =====================================================================

@api_view(["PUT"])
@transaction.atomic
def item_upsert(request):
    if (e := tekshir(request, "admin.norms")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    d = request.data
    nomi = str(d.get("nomi", "")).strip()
    if not nomi:
        return xato("Buyum nomi kiritilmadi")

    qiymat = {
        "nomi": nomi,
        "kod": str(d.get("kod", "")),
        "unit": str(d.get("unit") or "dona"),
        "qishki": bool(d.get("qishki")),
        "narx": son(d.get("narx")),
        "arxiv": bool(d.get("arxiv")),
    }

    iid = d.get("id")
    if iid and Item.objects.filter(id=iid).exists():
        Item.objects.filter(id=iid).update(**qiymat)
        item = Item.objects.get(id=iid)
    else:
        item = Item.objects.create(**qiymat)
        Stock.objects.get_or_create(item=item, defaults={"qoldiq": 0})

    audit(me, f"buyum {item.nomi}", "saqlandi")
    return holat(me)


@api_view(["PUT"])
@transaction.atomic
def norm_upsert(request):
    if (e := tekshir(request, "admin.norms")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    d = request.data

    position = Position.objects.filter(id=d.get("positionId")).first()
    item = Item.objects.filter(id=d.get("itemId")).first()
    if not position or not item:
        return xato("Lavozim yoki buyum topilmadi", status.HTTP_404_NOT_FOUND)

    muddat = d.get("muddatOy")
    muddat = None if muddat in ("", None) else int(muddat)

    norm, _ = Norm.objects.update_or_create(
        position=position,
        item=item,
        defaults={"muddat_oy": muddat, "qishki": bool(d.get("qishki"))},
    )
    audit(me, f"norma {norm.id}", "saqlandi")
    return holat(me)


@api_view(["DELETE"])
@transaction.atomic
def norm_delete(request, norm_id):
    if (e := tekshir(request, "admin.norms")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    adet, _ = Norm.objects.filter(id=norm_id).delete()
    if not adet:
        return xato("Norma topilmadi", status.HTTP_404_NOT_FOUND)

    audit(me, f"norma {norm_id}", "oʻchirildi")
    return holat(me)


# =====================================================================
# ISHCHI
# =====================================================================

@api_view(["PUT"])
@transaction.atomic
def worker_upsert(request):
    """Ishchi qoʻshish yoki tahrirlash. Yangi ishchiga kartochka va 3 ta talon ochiladi."""
    if (e := tekshir(request, "admin.users")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    from core.pin import valid_pin_format

    me = request.user
    d = request.data
    tabel = str(d.get("tabel", "")).strip()
    if not tabel:
        return xato("Tabel raqami kiritilmadi")

    position_ids = d.get("positionIds") or ([d["positionId"]] if d.get("positionId") else [])
    positions = list(Position.objects.filter(id__in=position_ids)) if position_ids else []

    qiymat = {
        "familiya": str(d.get("familiya", "")).strip(),
        "ism": str(d.get("ism", "")).strip(),
        "otasi": str(d.get("otasi", "") or ""),
        "sex": str(d.get("sex", "") or ""),
        "ish_joyi": str(d.get("ishJoyi", "") or ""),
        "kolonna": str(d.get("kolonna", "") or ""),
        "jinsi": d.get("jinsi") or "erkak",
        "boyi": int(son(d.get("boyi"))),
        "kiyim_olchami": str(d.get("kiyimOlchami", "") or ""),
        "poyabzal_olchami": str(d.get("poyabzalOlchami", "") or ""),
        "bosh_kiyim_olchami": str(d.get("boshKiyimOlchami", "") or ""),
        "telefon": str(d.get("telefon", "") or ""),
        "roles": d.get("roles") or ["ishchi"],
        "faol": bool(d.get("faol", True)),
        "imzo_id": str(d.get("imzoId", "") or ""),
        "position": positions[0] if positions else None,
    }
    if d.get("kirganSana"):
        qiymat["kirgan_sana"] = d["kirganSana"]
    if d.get("yoriqchiId"):
        qiymat["yoriqchi_id"] = d["yoriqchiId"]
    if d.get("faceImage"):
        qiymat["face_image"] = d["faceImage"]

    # Yangi ishchida id boʻlmaydi (yoki UUID emas) — oʻshanda yangi yozuv
    wid = uuid_yoki_none(d.get("id"))
    mavjud = Worker.objects.filter(id=wid).first() if wid else None

    # Tabel raqami takrorlanmasligi kerak
    band = Worker.objects.filter(tabel=tabel)
    if mavjud:
        band = band.exclude(id=mavjud.id)
    if band.exists():
        return xato(f"{tabel} tabel raqami boshqa ishchida band")

    # Admin ixtiyoriy ravishda boshlangʻich PIN belgilashi mumkin.
    # Belgilamasa ishchi birinchi kirishda oʻzi oʻrnatadi.
    pin = str(d.get("pin", "") or "").strip()
    if pin and not valid_pin_format(pin):
        return xato("PIN 4 xonali raqam boʻlishi kerak")

    if mavjud:
        for k, v in qiymat.items():
            setattr(mavjud, k, v)
        mavjud.tabel = tabel
        mavjud.save()
        worker = mavjud
        yangi = False
    else:
        worker = Worker.objects.create(depo=Depo.joriy(), tabel=tabel, **qiymat)
        worker.set_unusable_password()
        worker.save(update_fields=["password"])
        yangi = True

    if positions:
        worker.positions.set(positions)

    if yangi:
        Card.objects.get_or_create(worker=worker, defaults={"ochilgan": logic.today()})
        for r in (1, 2, 3):
            Talon.objects.get_or_create(worker=worker, raqam=r, defaults={"olingan": False})

    if pin:
        worker.set_pin(pin)
        worker.save(update_fields=["pin_hash", "pin_reset"])
        audit(me, f"ishchi {worker.tabel}", "boshlangʻich PIN oʻrnatildi")

    audit(me, f"ishchi {worker.tabel}", "qoʻshildi" if yangi else "saqlandi")
    javob = holat(me)
    javob.data["id"] = str(worker.id)
    javob.data["yangi"] = yangi
    return javob


@api_view(["POST"])
@transaction.atomic
def worker_import(request):
    """Ommaviy import — mavjud tabel raqamlari tashlab ketiladi."""
    if (e := tekshir(request, "admin.users")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    rows = request.data.get("rows") or []
    umumiy_pid = request.data.get("positionId")

    if not isinstance(rows, list) or not rows:
        return xato("Import uchun maʼlumot yuborilmadi")

    depo = Depo.joriy()
    mavjud = set(Worker.objects.values_list("tabel", flat=True))
    qoshildi = 0

    for r in rows:
        tabel = str(r.get("tabel", "")).strip()
        if not tabel or tabel in mavjud:
            continue

        pid = r.get("positionId") or umumiy_pid
        position = Position.objects.filter(id=pid).first() if pid else None

        w = Worker.objects.create(
            depo=depo,
            tabel=tabel,
            familiya=str(r.get("familiya", "")).strip(),
            ism=str(r.get("ism", "")).strip(),
            otasi=str(r.get("otasi", "") or "").strip(),
            position=position,
            ish_joyi=depo.nomi,
            kirgan_sana=logic.today(),
            jinsi="erkak",
            roles=["ishchi"],
            faol=True,
            face_image=str(r.get("faceImage", "") or ""),
        )
        w.set_unusable_password()
        w.save(update_fields=["password"])

        if position:
            w.positions.set([position])

        Card.objects.create(worker=w, ochilgan=logic.today())
        for n in (1, 2, 3):
            Talon.objects.create(worker=w, raqam=n, olingan=False)

        mavjud.add(tabel)
        qoshildi += 1

    audit(me, "ommaviy import", f"{qoshildi} ta ishchi qoʻshildi")
    javob = holat(me)
    javob.data["added"] = qoshildi
    return javob


@api_view(["DELETE"])
@transaction.atomic
def worker_delete(request, worker_id):
    """
    Ishchini oʻchirish — SOFT-DELETE.

    Yozuv bazadan yoʻqolmaydi: `deleted=True` qoʻyiladi. Sabab —
    ishchiga bogʻlangan tarix (arizalar, kartochka, imzolar, talonlar)
    buzilmasligi kerak. Hujjatlar yillar davomida saqlanadi va ularda
    kim imzolagani koʻrinib turishi shart.

    Uch qoida bilan himoyalangan:
      1. Oʻzini oʻchira olmaydi
      2. Oxirgi administratorni oʻchirib boʻlmaydi (tizim egasiz qolmasin)
      3. Barcha seanslari bekor qilinadi — oʻchirilgan odam kira olmaydi
    """
    if (e := tekshir(request, "admin.users")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    from core.tokens import revoke_all

    me = request.user
    worker = Worker.objects.filter(id=worker_id, deleted=False).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    if worker.id == me.id:
        return xato("Oʻzingizni oʻchira olmaysiz")

    if "admin" in (worker.roles or []):
        # `roles__contains` JSONField uchun SQLite'da qoʻllab-quvvatlanmaydi
        # (testlar va lokal muhit SQLite'da ishlaydi). Shuning uchun
        # sanoq Python tomonida — 800 ta yozuv uchun bu arzon.
        qolgan = sum(
            1
            for r in Worker.objects.filter(deleted=False, faol=True)
            .exclude(id=worker.id)
            .values_list("roles", flat=True)
            if "admin" in (r or [])
        )
        if qolgan == 0:
            return xato(
                "Bu tizimdagi yagona administrator — oʻchirib boʻlmaydi. "
                "Avval boshqa ishchiga administrator rolini bering"
            )

    worker.deleted = True
    worker.faol = False
    worker.save(update_fields=["deleted", "faol"])
    revoke_all(worker)

    audit(me, f"ishchi {worker.tabel}", "oʻchirildi", worker.fio)
    return holat(me)


@api_view(["DELETE"])
@transaction.atomic
def worker_face_reset(request, worker_id):
    """
    Ishchining Face ID'sini oʻchirish (admin).

    Kerak boʻladigan holatlar: notoʻgʻri yuz qayd etilgan, ishchining
    tashqi koʻrinishi keskin oʻzgargan, yoki hisob boshqa odamga
    oʻtkazilmoqda. Oʻchirilgach ishchi PIN bilan kiradi va kabinetidan
    yuzini qaytadan qoʻshadi.
    """
    if (e := tekshir(request, "admin.users")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    worker = Worker.objects.filter(id=worker_id, deleted=False).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    worker.face_vector = []
    worker.face_image = ""
    worker.save(update_fields=["face_vector", "face_image"])
    audit(me, f"ishchi {worker.tabel}", "Face ID oʻchirildi")

    return holat(me)


@api_view(["POST", "DELETE"])
@transaction.atomic
def worker_pin(request, worker_id):
    """
    POST   — ishchiga PIN oʻrnatish (admin).
    DELETE — PIN'ni oʻchirib, majburiy almashtirishga qoʻyish.
    """
    if (e := tekshir(request, "admin.users")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    from core.pin import valid_pin_format
    from core.tokens import revoke_all

    me = request.user
    worker = Worker.objects.filter(id=worker_id, deleted=False).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        worker.clear_pin()
        worker.save(update_fields=["pin_hash", "pin_reset"])
        revoke_all(worker)
        audit(me, f"ishchi {worker.tabel}", "PIN majburiy almashtirishga qoʻyildi")
    else:
        pin = str(request.data.get("pin", "")).strip()
        if not valid_pin_format(pin):
            return xato("PIN 4 xonali raqam boʻlishi kerak")
        worker.set_pin(pin)
        worker.save(update_fields=["pin_hash", "pin_reset"])
        revoke_all(worker)
        audit(me, f"ishchi {worker.tabel}", "PIN oʻrnatildi / tiklandi")

    return holat(me)


# =====================================================================
# LAVOZIM / BIRLIK / LINIYA
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def position_add(request):
    if (e := tekshir(request, "admin.settings")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    nomi = str(request.data.get("nomi", "")).strip()
    if not nomi:
        return xato("Lavozim nomi kiritilmadi")

    depo = Depo.joriy()
    oxirgi = Position.objects.filter(depo=depo).order_by("-tartib").values_list("tartib", flat=True).first() or 0
    p = Position.objects.create(depo=depo, nomi=nomi, tartib=oxirgi + 1)

    audit(me, f"lavozim {p.nomi}", "qoʻshildi")
    javob = holat(me)
    javob.data["id"] = str(p.id)
    return javob


@api_view(["PATCH"])
@transaction.atomic
def position_update(request, position_id):
    """Nomini oʻzgartirish va/yoki arxivlash."""
    if (e := tekshir(request, "admin.settings")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    p = Position.objects.filter(id=position_id).first()
    if not p:
        return xato("Lavozim topilmadi", status.HTTP_404_NOT_FOUND)

    if "nomi" in request.data:
        nomi = str(request.data["nomi"]).strip()
        if not nomi:
            return xato("Lavozim nomi boʻsh boʻlishi mumkin emas")
        p.nomi = nomi
        audit(me, f"lavozim {p.id}", "nomi oʻzgardi")

    if "arxiv" in request.data:
        p.arxiv = bool(request.data["arxiv"])
        audit(me, f"lavozim {p.nomi}", "arxivlandi" if p.arxiv else "tiklandi")

    p.save()
    return holat(me)


@api_view(["POST", "DELETE"])
@transaction.atomic
def unit_manage(request):
    if (e := tekshir(request, "admin.settings")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    nomi = str(request.data.get("nomi", "")).strip()
    if not nomi:
        return xato("Birlik nomi kiritilmadi")

    if request.method == "DELETE":
        Unit.objects.filter(nomi=nomi).delete()
        audit(me, f"birlik {nomi}", "oʻchirildi")
    else:
        oxirgi = Unit.objects.order_by("-tartib").values_list("tartib", flat=True).first() or 0
        Unit.objects.get_or_create(nomi=nomi, defaults={"tartib": oxirgi + 1})
        audit(me, f"birlik {nomi}", "qoʻshildi")

    return holat(me)


@api_view(["POST", "DELETE"])
@transaction.atomic
def line_manage(request):
    if (e := tekshir(request, "admin.settings")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    nomi = str(request.data.get("nomi", "")).strip()
    if not nomi:
        return xato("Liniya nomi kiritilmadi")

    if request.method == "DELETE":
        Line.objects.filter(nomi=nomi).delete()
        audit(me, f"liniya {nomi}", "oʻchirildi")
    else:
        oxirgi = Line.objects.order_by("-tartib").values_list("tartib", flat=True).first() or 0
        Line.objects.get_or_create(nomi=nomi, defaults={"tartib": oxirgi + 1})
        audit(me, f"liniya {nomi}", "qoʻshildi")

    return holat(me)


# =====================================================================
# RUXSATLAR
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def access_set(request):
    """
    Ruxsat/koʻrinish override'ini oʻrnatish yoki olib tashlash.

    Kutiladi: {scope: "role"|"position"|"user", scopeId, key, value}
    value = null boʻlsa override oʻchiriladi (standart holatga qaytadi).
    """
    if (e := tekshir(request, "admin.settings")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    scope = str(request.data.get("scope", ""))
    scope_id = str(request.data.get("scopeId", ""))
    key = str(request.data.get("key", ""))
    value = request.data.get("value", None)

    if scope not in ("role", "position", "user"):
        return xato("scope 'role', 'position' yoki 'user' boʻlishi kerak")
    if not scope_id or not key:
        return xato("scopeId va key koʻrsatilishi shart")

    if value is None:
        AccessOverride.objects.filter(scope=scope, scope_id=scope_id, key=key).delete()
        natija = "standart"
    else:
        AccessOverride.objects.update_or_create(
            scope=scope, scope_id=scope_id, key=key,
            defaults={"value": bool(value)},
        )
        natija = str(bool(value))

    audit(me, f"ruxsat {scope}:{scope_id}", f"{key} → {natija}")
    return holat(me)


# =====================================================================
# XODISALAR
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def incident_add(request):
    me = request.user
    turi = str(request.data.get("turi", ""))
    matn = str(request.data.get("matn", "")).strip()

    if turi not in ("tb", "avariya"):
        return xato("turi 'tb' yoki 'avariya' boʻlishi kerak")
    if not matn:
        return xato("Xabar matni boʻsh")

    perm = "incident.tb.write" if turi == "tb" else "incident.avariya.write"
    if (e := tekshir(request, perm)):
        return xato(e, status.HTTP_403_FORBIDDEN)

    Incident.objects.create(turi=turi, matn=matn, author=me)
    audit(me, "TB baxtsiz xodisa" if turi == "tb" else "Mashinist yoʻriqchisi avariyasi", "yozildi")
    return holat(me)


def _incident_nomi(turi: str) -> str:
    return "TB baxtsiz xodisa" if turi == "tb" else "Mashinist yoʻriqchisi avariyasi"


def _incident_tekshir(request, xodisa: Incident) -> str | None:
    """Yozuvni tahrirlash/oʻchirish huquqi bormi?

    Qoida: yozuvni MUALLIFI oʻzgartira oladi (shu turdagi yozish ruxsati
    boʻlsa), administrator esa istalganini. Shunda bir yoʻriqchi boshqa
    yoʻriqchining xabarini bildirmay tahrirlab yubormaydi.
    """
    me = request.user
    if worker_can(me, "admin.users"):
        return None

    perm = "incident.tb.write" if xodisa.turi == "tb" else "incident.avariya.write"
    if not worker_can(me, perm):
        return "Bu amal uchun ruxsatingiz yoʻq"
    if xodisa.author_id != me.id:
        return "Faqat oʻzingiz yozgan xabarni oʻzgartira olasiz"
    return None


@api_view(["PATCH", "DELETE"])
@transaction.atomic
def incident_manage(request, incident_id):
    """Xodisani tahrirlash (PATCH) yoki oʻchirish (DELETE)."""
    me = request.user
    xodisa = Incident.objects.filter(id=incident_id).first()
    if not xodisa:
        return xato("Xabar topilmadi", status.HTTP_404_NOT_FOUND)

    if (e := _incident_tekshir(request, xodisa)):
        return xato(e, status.HTTP_403_FORBIDDEN)

    if request.method == "DELETE":
        xodisa.delete()
        audit(me, _incident_nomi(xodisa.turi), "oʻchirildi")
        return holat(me)

    matn = str(request.data.get("matn", "")).strip()
    if not matn:
        return xato("Xabar matni boʻsh")

    xodisa.matn = matn
    xodisa.save(update_fields=["matn"])
    audit(me, _incident_nomi(xodisa.turi), "tahrirlandi")
    return holat(me)


# =====================================================================
# BILDIRISHNOMALAR
# =====================================================================

@api_view(["POST"])
@transaction.atomic
def notification_read(request):
    """Bildirishnomani (yoki hammasini) oʻqilgan deb belgilash."""
    me = request.user
    nid = request.data.get("id")

    qs = Notification.objects.filter(worker=me, oqilgan=False)
    if nid:
        qs = qs.filter(id=nid)
    qs.update(oqilgan=True)

    return holat(me)
