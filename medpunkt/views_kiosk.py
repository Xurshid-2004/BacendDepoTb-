"""
=====================================================================
Kiosk endpointlari — `X-API-Key` bilan (JWT emas).

  POST /api/v1/medpunkt/ingest   — oʻlchov (bitta yoki toʻplam)
  POST /api/v1/medpunkt/hodisa   — koʻrik yakunlanmagan hol
  GET  /api/v1/medpunkt/sync     — xodimlar roʻyxati + chegaralar

Kiosk aloqa uzilganda oʻlchovni buferda saqlaydi va keyin qayta
yuboradi — shuning uchun `unik_kalit` UNIQUE va yozuv idempotent:
takroriy yuborish yangi qator yaratmaydi.
=====================================================================
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.models import Worker
from medpunkt import logic
from medpunkt.kiosk_auth import kalit_tekshir
from medpunkt.models import Hodisa, IshchiMeyor, MedPunkt, Olchov, Sozlama
from medpunkt.serializers import sozlama_json

log = logging.getLogger("tb")

# Bitta soʻrovda qabul qilinadigan eng koʻp yozuv — bufer juda katta
# boʻlsa ham server tiqilib qolmasin.
TOPLAM_MAX = 200


def _ol(d: dict, *nomlar, default=None):
    """Bir necha nomdan birinchi topilganini oladi (camelCase / snake_case)."""
    for n in nomlar:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return default


def _punkt(d: dict) -> MedPunkt | None:
    """
    Kiosk oʻzini `medPunkt` kodi bilan tanishtiradi. Notanish kod kelsa
    yozuv avtomatik ochiladi.

    Kod umuman berilmasa: bazada bitta med-punkt boʻlsa — oʻsha (bitta
    kioskli depoda sozlashni soddalashtiradi), bir nechta boʻlsa — xato.
    """
    kod = str(_ol(d, "medPunkt", "med_punkt", "punkt", "kod", default="") or "").strip()
    if not kod:
        qs = MedPunkt.objects.all()[:2]
        return qs[0] if len(qs) == 1 else None

    nom = str(_ol(d, "medPunktNom", "nom", default="") or "").strip()
    punkt, yaratildi = MedPunkt.objects.get_or_create(
        kod=kod[:32], defaults={"nom": nom[:128]}
    )
    if yaratildi:
        log.info("Med-punkt avtomatik ochildi: %s", kod)
    elif nom and punkt.nom != nom[:128]:
        punkt.nom = nom[:128]
        punkt.save(update_fields=["nom"])
    return punkt


def _qatorlar(data, kalit: str) -> list[dict]:
    """Bitta obyekt ham, roʻyxat ham, `{kalit: [...]}` ham qabul qilinadi."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        ichki = data.get(kalit)
        if isinstance(ichki, list):
            return [x for x in ichki if isinstance(x, dict)]
        return [data] if data else []      # boʻsh tana — «yuborilmadi»
    return []


def _qiymatlar(d: dict) -> dict:
    """
    Xom natija. Kiosk uni `qiymatlar` ichida yuboradi; sodda qurilmalar
    esa yuza (flat) koʻrinishda — ikkalasi ham tushuniladi.
    """
    q = _ol(d, "qiymatlar", "values", default=None)
    if isinstance(q, dict):
        return dict(q)

    yigilgan: dict = {}
    for nom in ("mg_l", "mgL", "aktiv", "birlik", "rejim",
                "sistolik", "diastolik", "puls", "aritmiya"):
        if nom in d:
            yigilgan["mg_l" if nom == "mgL" else nom] = d[nom]
    return yigilgan


def _tasdiq(d: dict) -> dict:
    """
    Tasdiq belgilari uch holatli: True / False / None (tekshirilmagan).
    Kiosk suratni ham, yuz vektorini ham YUBORMAYDI — faqat shu belgilar.
    """
    t = _ol(d, "tasdiq", default=None)
    if not isinstance(t, dict):
        t = {"qr": _ol(d, "qr"), "face": _ol(d, "face"), "surat": _ol(d, "surat")}
    return {
        "qr": logic.uch_holat(t.get("qr")),
        "face": logic.uch_holat(t.get("face")),
        "surat": logic.uch_holat(t.get("surat")),
    }


# =====================================================================
# POST /ingest — oʻlchov
# =====================================================================

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def ingest(request):
    xato = kalit_tekshir(request)
    if xato is not None:
        return xato

    qatorlar = _qatorlar(request.data, "olchovlar")
    if not qatorlar:
        return Response({"error": "Oʻlchov maʼlumoti yuborilmadi"}, status=400)
    if len(qatorlar) > TOPLAM_MAX:
        return Response(
            {"error": f"Bir soʻrovda koʻpi bilan {TOPLAM_MAX} ta oʻlchov yuboriladi"},
            status=400,
        )

    sozlama = Sozlama.joriy()
    natijalar: list[dict] = []
    punkt_oxirgi: MedPunkt | None = None

    for xom in qatorlar:
        punkt = _punkt(xom)
        if punkt is None:
            natijalar.append({"ok": False, "error": "medPunkt kodi koʻrsatilmagan"})
            continue
        punkt_oxirgi = punkt

        tur = str(_ol(xom, "tur", "type", default="") or "").strip().lower()
        if tur not in ("alko", "qon"):
            natijalar.append({"ok": False, "error": f"notanish oʻlchov turi: {tur or '—'}"})
            continue

        vaqt = logic.vaqt_oqi(_ol(xom, "olchovVaqti", "olchov_vaqti", "vaqt", "time"))
        tabel = str(_ol(xom, "tabel", "tabelRaqami", "kartaId", "card", default="") or "").strip()
        sessiya = str(_ol(xom, "sessiyaId", "sessiya_id", "session", default="") or "").strip()
        qurilma = str(_ol(xom, "qurilma", "device", default="") or "").strip()

        unik = str(_ol(xom, "unikKalit", "unik_kalit", "uid", default="") or "").strip()
        if not unik:
            # Qurilma oʻz identifikatorini bermasa — mazmunidan yigʻamiz.
            # Bir xil oʻlchov qayta kelsa kalit ham bir xil chiqadi.
            unik = f"{qurilma}|{tur}|{vaqt.isoformat()}|{tabel}"

        qiymatlar = _qiymatlar(xom)
        worker = logic.worker_top(tabel)
        holat, izoh = logic.holat_hisobla(tur, qiymatlar, worker, sozlama, tabel)

        with transaction.atomic():
            olchov, yangi = Olchov.objects.get_or_create(
                unik_kalit=unik[:128],
                defaults={
                    "med_punkt": punkt,
                    "worker": worker,
                    "tabel": tabel[:32],
                    "sessiya_id": sessiya[:64],
                    "tur": tur,
                    "qurilma": qurilma[:64],
                    "olchov_vaqti": vaqt,
                    "qiymatlar": qiymatlar,
                    "tasdiq": _tasdiq(xom),
                    "face_masofa": logic.son(_ol(xom, "faceMasofa", "face_masofa")),
                    "egasiz": holat == "egasiz",
                    "holat": holat,
                    "izoh": izoh[:255],
                },
            )

        natijalar.append({
            "ok": True,
            "id": str(olchov.id),
            "unikKalit": olchov.unik_kalit,
            "yangi": yangi,          # False — takroriy yuborish, yozuv oʻzgarmadi
            "holat": olchov.holat,
            "izoh": olchov.izoh,
            "worker": worker.fio if worker else None,
        })

    if punkt_oxirgi is not None:
        MedPunkt.objects.filter(id=punkt_oxirgi.id).update(oxirgi_aloqa=timezone.now())

    qabul = sum(1 for n in natijalar if n.get("ok"))
    javob = {"ok": qabul > 0, "qabul": qabul, "jami": len(natijalar), "natijalar": natijalar}

    # Kiosk (METROBOT `outbox.rs`) server xulosasini javobning ENG YUQORI
    # darajasidan oʻqiydi va uni oʻz bazasiga `holat_server` sifatida
    # yozadi. U bitta oʻlchovni bitta soʻrovda yuboradi — shu holda
    # xulosani yuqoriga ham chiqaramiz. Toʻplamda maʼnosi yoʻq.
    if len(natijalar) == 1 and natijalar[0].get("ok"):
        javob["holat"] = natijalar[0]["holat"]
        javob["izoh"] = natijalar[0]["izoh"]

    return Response(javob, status=200 if qabul else 400)


# =====================================================================
# POST /hodisa — koʻrik yakunlanmagan hol
# =====================================================================

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def hodisa(request):
    xato = kalit_tekshir(request)
    if xato is not None:
        return xato

    qatorlar = _qatorlar(request.data, "hodisalar")
    if not qatorlar:
        return Response({"error": "Hodisa maʼlumoti yuborilmadi"}, status=400)
    if len(qatorlar) > TOPLAM_MAX:
        return Response(
            {"error": f"Bir soʻrovda koʻpi bilan {TOPLAM_MAX} ta hodisa yuboriladi"},
            status=400,
        )

    yozildi: list[str] = []
    punkt_oxirgi: MedPunkt | None = None

    for xom in qatorlar:
        punkt = _punkt(xom)
        if punkt is None:
            continue
        punkt_oxirgi = punkt

        tur = str(_ol(xom, "tur", "type", default="boshqa") or "boshqa").strip()
        tabel = str(_ol(xom, "tabel", "tabelRaqami", "kartaId", default="") or "").strip()
        sessiya = str(_ol(xom, "sessiyaId", "sessiya_id", default="") or "").strip()
        tafsilot = str(_ol(xom, "tafsilot", "izoh", "detail", default="") or "").strip()
        vaqt = logic.vaqt_oqi(_ol(xom, "vaqt", "time", "olchovVaqti"))

        # Sessiya boʻyicha takrorni toʻxtatamiz — kiosk buferi qayta
        # yuborsa, bir xil hodisa ikki marta yozilmaydi.
        mavjud = None
        if sessiya:
            mavjud = Hodisa.objects.filter(
                med_punkt=punkt, sessiya_id=sessiya[:64], tur=tur[:32], vaqt=vaqt
            ).first()
        if mavjud is not None:
            yozildi.append(str(mavjud.id))
            continue

        h = Hodisa.objects.create(
            med_punkt=punkt,
            worker=logic.worker_top(tabel),
            tur=tur[:32],
            tabel=tabel[:32],
            sessiya_id=sessiya[:64],
            tafsilot=tafsilot[:255],
            vaqt=vaqt,
        )
        yozildi.append(str(h.id))

    if punkt_oxirgi is not None:
        MedPunkt.objects.filter(id=punkt_oxirgi.id).update(oxirgi_aloqa=timezone.now())

    if not yozildi:
        return Response({"error": "Hodisa yozilmadi — medPunkt kodi koʻrsatilmagan"}, status=400)
    return Response({"ok": True, "qabul": len(yozildi), "idlar": yozildi})


# =====================================================================
# GET /sync — xodimlar va chegaralar
# =====================================================================

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def sync(request):
    """
    Kiosk ishga tushganda va vaqti-vaqti bilan shu roʻyxatni oladi:
    kim QR koʻrsatsa uni oflayn holatda ham taniy olishi uchun.

    Yuz vektori ham, surat ham berilmaydi — kioskka ular kerak emas.
    """
    xato = kalit_tekshir(request)
    if xato is not None:
        return xato

    punkt = _punkt(request.query_params.dict())
    if punkt is not None:
        MedPunkt.objects.filter(id=punkt.id).update(oxirgi_aloqa=timezone.now())

    meyorlar = {
        str(m.worker_id): {
            "sisMax": m.sis_max, "diaMax": m.dia_max,
            "pulsMin": m.puls_min, "pulsMax": m.puls_max,
        }
        for m in IshchiMeyor.objects.filter(deleted=False)
    }

    xodimlar = [
        {
            "id": str(w.id),
            "tabel": w.tabel,
            "fio": w.fio,
            "kolonna": w.kolonna_ref.nomi if w.kolonna_ref_id else (w.kolonna or ""),
            "lavozim": w.position.nomi if w.position_id else "",
            "meyor": meyorlar.get(str(w.id)),
        }
        for w in Worker.objects.filter(faol=True, deleted=False)
        .select_related("position", "kolonna_ref")
        .order_by("tabel")
    ]

    return Response({
        "ok": True,
        "vaqt": timezone.now().isoformat(),
        "medPunkt": punkt.kod if punkt else None,
        "sozlamalar": sozlama_json(Sozlama.joriy()),
        "xodimlar": xodimlar,
        "jami": len(xodimlar),
    })
