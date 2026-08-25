"""
=====================================================================
Yoʻriqnoma kitobchalari — TNU-19 (Yo D-26A) va instruktor (Yo D-26B).

Oqim (TNU-19):
  1. Depo navbatchisi smenani boshlaydi — mazmun/xulosani bir marta kiritadi.
  2. Ishchi keladi → navbatchi barkod bilan ID kartani skanerlaydi
     (POST /yoriqnoma/skan {payload}) → qator avtomatik yaratiladi:
     sana, F.I.Sh., lavozim qisqartma, JORIY turi, mazmun/xulosa
     smenadan koʻchiriladi va ishchining QR imzosi (9-ustun) darhol qoʻyiladi.
  3. Navbatchi «Tasdiqlayman» (POST /yoriqnoma/tasdiqla/<id>) — oʻz QR
     imzosini (8-ustun) qoʻyadi.

Barcha imzolar yagona Signature tizimida. Kitob 700 bet toʻlgach avtomatik
yangi kitob ochiladi, eskisi arxivga oʻtadi.
=====================================================================
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from api.serializers import build_state
from api.views_ops import audit, holat, tekshir, xato
from core import imzo, logic
from core.models import (
    Kitob, Kolonna, Signature, Smena, Worker, YoriqnomaVaraq, YoriqnomaYozuv,
)

QATOR_PER_BET = 20  # TNU-19 varagʻida ~20 qator


# ---------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------

def aktiv_kitob(turi: str, kolonna: Kolonna | None = None) -> Kitob:
    """Ochiq (arxivlanmagan) kitobni qaytaradi, boʻlmasa yaratadi."""
    qs = Kitob.objects.filter(turi=turi, arxiv=False, kolonna=kolonna)
    kitob = qs.order_by("-raqam").first()
    if kitob:
        return kitob
    oxirgi = Kitob.objects.filter(turi=turi, kolonna=kolonna).order_by("-raqam").first()
    raqam = (oxirgi.raqam + 1) if oxirgi else 1
    return Kitob.objects.create(turi=turi, kolonna=kolonna, raqam=raqam, joriy_bet=1)


def joyla(kitob: Kitob) -> tuple[Kitob, int, int]:
    """Keyingi (bet, qator)ni qaytaradi; kerak boʻlsa yangi bet/kitob ochadi."""
    band = YoriqnomaYozuv.objects.filter(kitob=kitob, bet=kitob.joriy_bet).count()
    if band >= QATOR_PER_BET:
        kitob.joriy_bet += 1
        if kitob.joriy_bet > kitob.sigim:
            # kitob toʻldi — arxivga, yangisini ochamiz
            kitob.arxiv = True
            kitob.yopilgan = timezone.now()
            kitob.save(update_fields=["arxiv", "yopilgan"])
            kitob = aktiv_kitob(kitob.turi, kitob.kolonna)
            return kitob, 1, 1
        kitob.save(update_fields=["joriy_bet"])
        band = 0
    return kitob, kitob.joriy_bet, band + 1


def oluvchi_imzo_yarat(worker: Worker, doc_type: str, doc_id) -> Signature:
    """Kartasi skanerlangan ishchining QR imzosi (oluvchi/oʻtuvchi)."""
    sana_iso = timezone.now().isoformat()
    payload = {
        "sana": sana_iso,
        "fio": worker.fio,
        "lavozim": worker.position.nomi if worker.position else "",
        "tabel": worker.tabel,
    }
    return Signature.objects.create(
        doc_type=doc_type, doc_id=str(doc_id), field="9", user=worker,
        hash=imzo.doc_hmac(doc_type, doc_id, "9", worker.id, sana_iso),
        payload=payload,
    )


def instruktor_kolonna(me: Worker):
    """Foydalanuvchi instruktor boʻlgan faol kolonna (boʻlmasa None)."""
    return Kolonna.objects.filter(instruktor=me, faol=True).first()


def varaq_ol(kitob: Kitob, ishchi: Worker) -> YoriqnomaVaraq:
    """Ishchining shu instruktor kitobidagi varagʻi — boʻlmasa yangi bet ochadi."""
    varaq = YoriqnomaVaraq.objects.filter(kitob=kitob, ishchi=ishchi).first()
    if varaq:
        return varaq
    oxirgi = YoriqnomaVaraq.objects.filter(kitob=kitob).order_by("-bet").first()
    bet = (oxirgi.bet + 1) if oxirgi else 1
    return YoriqnomaVaraq.objects.create(kitob=kitob, ishchi=ishchi, bet=bet)


# ---------------------------------------------------------------------
# Smena
# ---------------------------------------------------------------------

@api_view(["POST"])
@transaction.atomic
def smena_boshla(request):
    """
    Depo navbatchisi smenasini boshlaydi yoki joriy smena matnini yangilaydi.
    {tur: "kunduzgi"|"tungi", mazmun, xulosa}
    """
    if (e := tekshir(request, "yoriqnoma.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    d = request.data
    tur = str(d.get("tur", "")).strip()
    if tur not in ("kunduzgi", "tungi"):
        return xato("Smena turi notoʻgʻri (kunduzgi/tungi)")

    smena = Smena.objects.filter(navbatchi=me, faol=True).first()
    if smena:
        smena.tur = tur
        smena.mazmun = str(d.get("mazmun", smena.mazmun) or "")
        smena.xulosa = str(d.get("xulosa", smena.xulosa) or "")
        smena.save(update_fields=["tur", "mazmun", "xulosa"])
        audit(me, "smena", "yangilandi")
    else:
        smena = Smena.objects.create(
            navbatchi=me, tur=tur,
            mazmun=str(d.get("mazmun", "") or ""),
            xulosa=str(d.get("xulosa", "") or ""),
        )
        audit(me, "smena", "boshlandi", tur)
    return holat(me)


@api_view(["POST"])
@transaction.atomic
def smena_yop(request):
    """Joriy smenani yopadi."""
    if (e := tekshir(request, "yoriqnoma.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)
    me = request.user
    smena = Smena.objects.filter(navbatchi=me, faol=True).first()
    if smena:
        smena.faol = False
        smena.tugagan = timezone.now()
        smena.save(update_fields=["faol", "tugagan"])
        audit(me, "smena", "yopildi")
    return holat(me)


# ---------------------------------------------------------------------
# Skan → qator yaratish
# ---------------------------------------------------------------------

@api_view(["POST"])
@transaction.atomic
def skan(request):
    """
    ID karta QR'i skanerlanganda qator yaratadi.
    {payload: "<QR butun matni>"} yoki {tabel, imzo}.
    Marshrut kirgan foydalanuvchi roli boʻyicha: depo_navbatchisi → TNU-19.
    (Instruktor yoʻli — keyingi bosqichda.)
    """
    if (e := tekshir(request, "yoriqnoma.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    roles = me.roles or []
    d = request.data

    # --- Marshrutlash: qaysi kitobga yoziladi (kirgan rol boʻyicha) ---
    kitob_turi = str(d.get("kitobTuri", "") or "").strip()
    navb = ("depo_navbatchisi" in roles) or ("admin" in roles)
    instr_kol = instruktor_kolonna(me) if (("yoriqchi" in roles) or ("admin" in roles)) else None
    instr = instr_kol is not None

    if not kitob_turi:
        if navb and not instr:
            kitob_turi = "tnu19"
        elif instr and not navb:
            kitob_turi = "instruktor"
        elif navb and instr:
            # Ikki rol — foydalanuvchi tanlashi kerak (imzolar aralashmasin)
            return Response({"tanlovKerak": True,
                             "error": "Qaysi kitobga yozamiz? (tnu19 yoki instruktor)"},
                            status=status.HTTP_409_CONFLICT)
        else:
            return xato("Yoʻriqnoma yozish uchun depo navbatchisi yoki instruktor roli kerak",
                        status.HTTP_403_FORBIDDEN)

    if kitob_turi == "instruktor" and instr_kol is None:
        return xato("Sizga kolonna biriktirilmagan — instruktor kitobi ochilmaydi",
                    status.HTTP_409_CONFLICT)
    if kitob_turi == "tnu19" and not navb:
        return xato("TNU-19 ga faqat depo navbatchisi yozadi", status.HTTP_403_FORBIDDEN)

    # --- Kartani oʻqib, ishchini topamiz ---
    payload = str(d.get("payload", "") or "").strip()
    tabel = str(d.get("tabel", "") or "").strip()
    taqdim = str(d.get("imzo", "") or "").strip()
    if payload and not (tabel and taqdim):
        p = imzo.parse_card_qr(payload)
        tabel = tabel or p["tabel"]
        taqdim = taqdim or p["imzo"]
    if not tabel:
        return xato("Karta oʻqilmadi (tabel aniqlanmadi)")

    w = Worker.objects.filter(tabel=tabel, deleted=False, faol=True).first()
    if not w and (t4 := imzo.tabel4(tabel)):
        w = Worker.objects.filter(tabel=t4, deleted=False, faol=True).first()
    if not w:
        audit(me, "yoriqnoma skan", "ishchi topilmadi", f"tabel: {tabel}")
        return xato(f"Ishchi topilmadi (tabel: {tabel})", status.HTTP_404_NOT_FOUND)

    # Karta imzosini tekshiramiz (yagona imzo tizimi)
    sig = None
    if w.imzo_id:
        sig = Signature.objects.filter(id=w.imzo_id, doc_type="card_id").first()
    if not sig:
        sig = Signature.objects.filter(doc_type="card_id", doc_id=str(w.id)).order_by("-sana").first()
    if not sig or not imzo.card_verify(sig.hash, taqdim):
        audit(me, "yoriqnoma skan", "karta yaroqsiz", f"{w.tabel} / {taqdim}")
        return xato("Karta imzosi yaroqsiz — qator yaratilmadi", status.HTTP_400_BAD_REQUEST)

    lavozim_q = logic.lavozim_qisqa(w.position.nomi if w.position else "")
    doc_type = "tnu19" if kitob_turi == "tnu19" else "yo_d26b"

    # ================= TNU-19 (depo navbatchisi) =================
    if kitob_turi == "tnu19":
        smena = Smena.objects.filter(navbatchi=me, faol=True).first()
        if not smena:
            return xato("Avval smenani boshlang (mazmun/xulosa kiriting)",
                        status.HTTP_409_CONFLICT)
        kitob = aktiv_kitob("tnu19")
        kitob, bet, qator = joyla(kitob)
        yozuv = YoriqnomaYozuv.objects.create(
            kitob=kitob, smena=smena, bet=bet, qator=qator,
            ishchi=w, lavozim_qisqa=lavozim_q,
            yoriq_turi="joriy", mazmun=smena.mazmun, xulosa=smena.xulosa,
            beruvchi=me, beruvchi_lavozim=(me.position.nomi if me.position else ""),
        )

    # ================= Instruktor (Yo D-26B) =================
    else:
        # Ishchi shu instruktor kolonnasiga tegishli boʻlishi shart
        if w.kolonna_ref_id != instr_kol.id:
            audit(me, "yoriqnoma skan", "boshqa kolonna", f"{w.tabel}")
            return xato("Bu ishchi sizning kolonnangizda emas — bloklanadi",
                        status.HTTP_403_FORBIDDEN)
        yoriq_turi = str(d.get("yoriqTuri", "davriy") or "davriy").strip()
        if yoriq_turi not in ("birlamchi", "navbatdan", "davriy"):
            yoriq_turi = "davriy"
        kitob = aktiv_kitob("instruktor", instr_kol)
        varaq = varaq_ol(kitob, w)
        qator = YoriqnomaYozuv.objects.filter(varaq=varaq).count() + 1
        yozuv = YoriqnomaYozuv.objects.create(
            kitob=kitob, varaq=varaq, bet=varaq.bet, qator=qator,
            ishchi=w, lavozim_qisqa=lavozim_q,
            yoriq_turi=yoriq_turi, mazmun=str(d.get("mazmun", "") or ""),
            beruvchi=me, beruvchi_lavozim=(me.position.nomi if me.position else ""),
        )

    # Oluvchi (ishchi) QR imzosi darhol — ikkala kitob uchun ham
    yozuv.oluvchi_imzo = oluvchi_imzo_yarat(w, doc_type, yozuv.id)
    yozuv.save(update_fields=["oluvchi_imzo"])

    audit(me, "yoriqnoma", "qator qoʻshildi", f"{kitob_turi}: {w.tabel}")
    javob = holat(me)
    javob.data["id"] = str(yozuv.id)
    return javob


@api_view(["POST"])
@transaction.atomic
def tasdiqla(request, yozuv_id):
    """
    «Tasdiqlayman» — beruvchi (navbatchi/instruktor) oʻz QR imzosini qoʻyadi.
    Instruktor kitobi uchun tasdiqlashdan oldin tur/mazmunni ham yuborishi
    mumkin ({yoriqTuri, mazmun}) — ular saqlanadi.
    """
    if (e := tekshir(request, "yoriqnoma.write")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    y = YoriqnomaYozuv.objects.select_for_update().select_related("kitob").filter(id=yozuv_id).first()
    if not y:
        return xato("Yozuv topilmadi", status.HTTP_404_NOT_FOUND)
    if y.tasdiqlangan and y.beruvchi_imzo_id:
        return xato("Bu yozuv allaqachon tasdiqlangan", status.HTTP_409_CONFLICT)

    d = request.data
    yangilanadi = []
    if y.kitob.turi == "instruktor":
        yt = str(d.get("yoriqTuri", "") or "").strip()
        if yt in ("birlamchi", "navbatdan", "davriy"):
            y.yoriq_turi = yt
            yangilanadi.append("yoriq_turi")
        if "mazmun" in d:
            y.mazmun = str(d.get("mazmun", "") or "")
            yangilanadi.append("mazmun")

    doc_type = "tnu19" if y.kitob.turi == "tnu19" else "yo_d26b"
    field = "8" if y.kitob.turi == "tnu19" else "5"

    from api.views_ops import imzo_yarat
    y.beruvchi_imzo = imzo_yarat(me, doc_type, y.id, field)
    y.tasdiqlangan = True
    y.save(update_fields=["beruvchi_imzo", "tasdiqlangan", *yangilanadi])
    audit(me, "yoriqnoma", "tasdiqlandi", str(y.id))
    return holat(me)


# ---------------------------------------------------------------------
# Kitobni oʻqish (sahifalab)
# ---------------------------------------------------------------------

@api_view(["GET"])
def kitoblar_royxati(request):
    """
    Foydalanuvchi koʻra oladigan kitoblar roʻyxati (monitoring/arxiv uchun).
    admin/depo_boshligi → hammasi; navbatchi → TNU-19; instruktor → oʻz kolonnasi.
    """
    if (e := tekshir(request, "yoriqnoma.read")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    me = request.user
    roles = me.roles or []
    hammasi = ("admin" in roles) or ("depo_boshligi" in roles)

    qs = Kitob.objects.select_related("kolonna", "kolonna__instruktor").order_by("turi", "kolonna__nomi", "-raqam")
    if not hammasi:
        kol = instruktor_kolonna(me)
        from django.db.models import Q
        shart = Q(turi="tnu19", kolonna=None) if (("depo_navbatchisi" in roles)) else Q(pk__in=[])
        if kol:
            shart = shart | Q(turi="instruktor", kolonna=kol)
        qs = qs.filter(shart)

    out = []
    for k in qs:
        out.append({
            "id": str(k.id), "turi": k.turi, "raqam": k.raqam,
            "kolonnaNomi": k.kolonna.nomi if k.kolonna else "Umumiy (TNU-19)",
            "kolonnaTuri": (k.kolonna.turi if k.kolonna else ""),
            "instruktorFio": (k.kolonna.instruktor.fio if (k.kolonna and k.kolonna.instruktor) else ""),
            "arxiv": k.arxiv, "joriyBet": k.joriy_bet, "sigim": k.sigim,
            "yozuvSoni": YoriqnomaYozuv.objects.filter(kitob=k).count(),
        })
    return Response({"kitoblar": out})


@api_view(["GET"])
def kitob_ol(request):
    """
    Kitob qatorlarini oʻqiydi (holatni shishirmaslik uchun alohida).
    ?turi=tnu19&kitobId=&bet=   — kitobId boʻsh boʻlsa aktiv kitob.
    """
    if (e := tekshir(request, "yoriqnoma.read")):
        return xato(e, status.HTTP_403_FORBIDDEN)

    from api.serializers import yoriqnoma_yozuv_json

    turi = request.query_params.get("turi", "tnu19")
    kitob_id = request.query_params.get("kitobId")
    if kitob_id:
        kitob = Kitob.objects.filter(id=kitob_id).first()
    elif turi == "instruktor":
        # Instruktor oʻz kolonnasining kitobini koʻradi
        kol = instruktor_kolonna(request.user)
        kitob = Kitob.objects.filter(turi="instruktor", arxiv=False, kolonna=kol).order_by("-raqam").first() if kol else None
    else:
        kitob = Kitob.objects.filter(turi="tnu19", arxiv=False, kolonna=None).order_by("-raqam").first()
    if not kitob:
        return Response({"kitob": None, "yozuvlar": []})

    yozuvlar = (
        YoriqnomaYozuv.objects.filter(kitob=kitob)
        .select_related("ishchi", "beruvchi", "oluvchi_imzo", "beruvchi_imzo")
        .order_by("bet", "qator")
    )
    return Response({
        "kitob": {
            "id": str(kitob.id), "turi": kitob.turi, "raqam": kitob.raqam,
            "joriyBet": kitob.joriy_bet, "sigim": kitob.sigim, "arxiv": kitob.arxiv,
        },
        "yozuvlar": [yoriqnoma_yozuv_json(y) for y in yozuvlar],
    })
