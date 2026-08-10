"""
=====================================================================
Autentifikatsiya endpointlari.

  POST /api/v1/auth/login      {tabel, pin}       → {access, refresh, user}
  POST /api/v1/auth/set-pin    {tabel, pin}       → {ok}
  POST /api/v1/auth/refresh    {refresh}          → {access}
  POST /api/v1/auth/logout     {refresh}          → {ok}
  GET  /api/v1/me                                 → foydalanuvchi + ruxsatlar
  POST /api/v1/admin/reset-pin {userId|tabel,pin} → {ok, mode}

MUHIM: PIN endi FAQAT shu yerda — serverda — tekshiriladi. Ilgari uni
brauzer tekshirardi va buning uchun barcha hash'lar mijozga
yuborilardi. Endi hash hech qachon serverdan chiqmaydi.
=====================================================================
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from api.serializers import me_json
from core import face, tokens
from core.models import AuditLog, Worker
from core.permissions import IsAdmin
from core.pin import valid_pin_format

log = logging.getLogger("tb")


def fio_niqob(w: Worker) -> str:
    """
    "Abduvaliyev Ohun Olimjon oʻgʻli" → "Abduvaliyev O. O."

    Roʻyxatdan oʻtayotgan odam toʻgʻri yozuvni tanlaganini tasdiqlashi
    uchun yetarli, ammo tabel raqamlarini terib toʻliq ismlar roʻyxatini
    yigʻib olish uchun yetarli emas.
    """
    bosh = [x[0].upper() + "." for x in (w.ism, w.otasi) if x]
    return " ".join([w.familiya, *bosh]).strip()


# Bitta kadrning eng katta hajmi (base64 belgilarda ≈ 1.5 MB surat).
# Chegara boʻlmasa mijoz 25 MB'lik suratlar yuborib, bazani ham,
# yuz tanish xizmatini ham bogʻlab qoʻyishi mumkin.
MAX_KADR_BELGI = 2_000_000
MAX_KADR_SONI = 5


def kadrlar_ol(request) -> list[str]:
    """
    Soʻrovdan yuz kadrlarini oladi (data URL roʻyxati).

    Haddan katta yoki notoʻgʻri formatdagi kadrlar tashlab ketiladi —
    bu yerda xato koʻtarilmaydi, chaqiruvchi boʻsh roʻyxatni oʻzi
    hal qiladi (kamera yoʻq holati bilan bir xil).
    """
    xom = request.data.get("frames") or []
    if not isinstance(xom, list):
        return []

    natija: list[str] = []
    for k in xom[:MAX_KADR_SONI]:
        if not isinstance(k, str):
            continue
        k = k.strip()
        if not k or len(k) > MAX_KADR_BELGI:
            continue
        # Faqat data URL qabul qilinadi — tashqi manzil yuborib
        # serverni boshqa xostga soʻrov yuborishga majburlab boʻlmaydi (SSRF).
        if not k.startswith("data:image/"):
            continue
        natija.append(k)
    return natija


def xato(matn: str, kod: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": matn}, status=kod)


class LoginThrottle(ScopedRateThrottle):
    scope = "login"


def _agent(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:255]


def _audit(worker: Worker | None, obyekt: str, amal: str, izoh: str = "") -> None:
    AuditLog.objects.create(user=worker, obyekt=obyekt, amal=amal, izoh=izoh)


# ---------------------------------------------------------------------
# Kirish
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    tabel = str(request.data.get("tabel", "")).strip()
    pin = str(request.data.get("pin", "")).strip()

    if not tabel:
        return xato("Tabel raqami kiritilmadi")

    worker = (
        Worker.objects.filter(tabel=tabel, deleted=False)
        .select_related("depo", "position")
        .first()
    )

    # Ishchi topilmasa ham bir xil xabar — tabel raqamlarini terib
    # koʻrishning maʼnosi boʻlmasligi uchun.
    if not worker or not worker.faol:
        return xato("Tabel raqami yoki PIN notoʻgʻri", status.HTTP_401_UNAUTHORIZED)

    # PIN hali oʻrnatilmagan yoki majburiy almashtirishga qoʻyilgan.
    # `royxatKerak` — hech qachon roʻyxatdan oʻtmagan (admin import
    # qilgan, lekin ishchi oʻzi hali PIN/yuz bermagan). Veb-ilova uni
    # roʻyxatdan oʻtish oqimiga yoʻnaltiradi.
    # `needsPin` esa Flutter ilovasi bilan moslik uchun saqlanadi.
    if not worker.pin_hash or worker.pin_reset:
        return Response({
            "needsPin": True,
            "royxatKerak": not worker.pin_hash and worker.royxatdan_otgan is None,
            "tabel": worker.tabel,
        })

    if not pin:
        return xato("PIN kiritilmadi")

    if not worker.check_pin(pin):
        _audit(worker, f"kirish {tabel}", "notoʻgʻri PIN")
        return xato("Tabel raqami yoki PIN notoʻgʻri", status.HTTP_401_UNAUTHORIZED)

    juftlik = tokens.token_juftligi(worker, _agent(request))
    worker.last_login = timezone.now()
    worker.save(update_fields=["last_login"])
    _audit(worker, f"kirish {tabel}", "muvaffaqiyatli")

    return Response({**juftlik, "user": me_json(worker)})


# ---------------------------------------------------------------------
# Tabel raqamini tekshirish — kirish formasi birinchi qadami
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def check(request):
    """
    {tabel} → ishchi bormi va keyingi qadam nima.

    Javob:
      bor           — kadrlar bazasida shunday tabel bormi
      royxatKerak   — hali roʻyxatdan oʻtmagan (yuz/PIN yoʻq)
      pinKerak      — PIN majburiy almashtirishga qoʻyilgan
      faceBor       — ishchining saqlangan yuz vektori bormi
      faceYoqilgan  — yuz tanish xizmati umuman sozlanganmi
      fio           — niqoblangan F.I.Sh. (tasdiqlash uchun)

    Bu endpoint kirish bilan bir xil tezlikda cheklanadi (throttle) —
    tabel raqamlarini ketma-ket terib chiqishning oldi olinadi.
    """
    tabel = str(request.data.get("tabel", "")).strip()
    if not tabel:
        return xato("Tabel raqami kiritilmadi")

    worker = Worker.objects.filter(tabel=tabel, deleted=False, faol=True).first()
    if not worker:
        return Response({"bor": False})

    return Response({
        "bor": True,
        "royxatKerak": not worker.pin_hash and worker.royxatdan_otgan is None,
        "pinKerak": bool(worker.pin_hash) and worker.pin_reset,
        "faceBor": bool(worker.face_vector),
        "faceYoqilgan": face.yoqilganmi(),
        "fio": fio_niqob(worker),
    })


# ---------------------------------------------------------------------
# Roʻyxatdan oʻtish — ishchi oʻzi yuzini beradi va PIN qoʻyadi
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def register(request):
    """
    {tabel, pin, frames[]} → {access, refresh, user, faceSaqlandi}

    Faqat kadrlar bazasida BOR (admin qoʻshgan yoki ommaviy import
    qilgan) tabel raqami roʻyxatdan oʻta oladi. Yangi ishchi shu
    yerdan yaratilmaydi — bu ataylab: tizimga faqat depo kadrlar
    boʻlimi kiritgan odam kira oladi.

    Kamera boʻlmasa `frames` boʻsh keladi — PIN bilan roʻyxatdan
    oʻtiladi, Face ID keyin qoʻshiladi.
    """
    tabel = str(request.data.get("tabel", "")).strip()
    pin = str(request.data.get("pin", "")).strip()
    kadrlar = kadrlar_ol(request)

    if not tabel:
        return xato("Tabel raqami kiritilmadi")
    if not valid_pin_format(pin):
        return xato("PIN 4 xonali raqam boʻlishi kerak")

    worker = Worker.objects.filter(tabel=tabel, deleted=False, faol=True).first()
    if not worker:
        return xato(
            "Bu tabel raqami kadrlar bazasida topilmadi. "
            "Depo kadrlar boʻlimiga murojaat qiling",
            status.HTTP_404_NOT_FOUND,
        )

    # Ikki marta roʻyxatdan oʻtib boʻlmaydi — aks holda birov boshqaning
    # hisobiga oʻz yuzini biriktirib olishi mumkin edi.
    if worker.pin_hash or worker.royxatdan_otgan is not None:
        return xato(
            "Bu tabel raqami allaqachon roʻyxatdan oʻtgan. "
            "Kirish boʻlimidan foydalaning yoki administratorga murojaat qiling",
            status.HTTP_409_CONFLICT,
        )

    # --- yuzni vektorlash (ixtiyoriy) ---
    face_saqlandi = False
    face_xabar = ""
    if kadrlar:
        try:
            worker.face_vector = face.vektor(kadrlar[0])
            worker.face_image = kadrlar[0]
            face_saqlandi = True
        except face.FaceXato as e:
            # Suratda yuz yoʻq — buni foydalanuvchi tuzatishi mumkin,
            # shuning uchun roʻyxatdan oʻtishni toʻxtatamiz.
            return xato(str(e) or "Suratda yuz aniqlanmadi — qayta urinib koʻring")
        except RuntimeError:
            # Servis oʻchiq — roʻyxatdan oʻtish toʻxtamaydi, PIN bilan davom etadi
            face_xabar = (
                "Yuz tanish xizmati hozir ishlamayapti — PIN bilan roʻyxatdan "
                "oʻtdingiz. Face ID'ni keyinroq kabinetdan qoʻshasiz"
            )

    with transaction.atomic():
        worker.set_pin(pin)
        worker.royxatdan_otgan = timezone.now()
        worker.save(update_fields=[
            "pin_hash", "pin_reset", "face_vector", "face_image", "royxatdan_otgan",
        ])
        _audit(
            worker,
            f"ishchi {worker.tabel}",
            "roʻyxatdan oʻtdi",
            "Face ID bilan" if face_saqlandi else "faqat PIN",
        )

    juftlik = tokens.token_juftligi(worker, _agent(request))
    return Response({
        "ok": True,
        **juftlik,
        "user": me_json(worker),
        "faceSaqlandi": face_saqlandi,
        "faceXabar": face_xabar,
    })


# ---------------------------------------------------------------------
# Yuz bilan kirish
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def face_login(request):
    """
    {tabel, frames[]} → {access, refresh, user}

    Bir nechta kadr yuboriladi — jonlilik tekshiruvi uchun (ekranga
    tutilgan surat bilan kirishning oldini oladi).

    Yuz mos kelmasa 401 qaytadi va frontend PIN'ga oʻtadi — bu
    ataylab: yuz tanish qulaylik, PIN esa kafolatlangan yoʻl.
    """
    tabel = str(request.data.get("tabel", "")).strip()
    kadrlar = kadrlar_ol(request)

    if not tabel:
        return xato("Tabel raqami kiritilmadi")
    if len(kadrlar) < 2:
        return xato("Kamida 2 ta kadr kerak")

    worker = (
        Worker.objects.filter(tabel=tabel, deleted=False, faol=True)
        .select_related("depo", "position")
        .first()
    )
    if not worker or not worker.face_vector:
        return xato("Yuz bilan kirish bu hisob uchun sozlanmagan — PIN bilan kiring",
                    status.HTTP_401_UNAUTHORIZED)

    if worker.pin_reset:
        return xato("PIN majburiy almashtirishga qoʻyilgan — PIN bilan kiring",
                    status.HTTP_401_UNAUTHORIZED)

    try:
        natija = face.tekshir(kadrlar, worker.face_vector)
    except face.FaceXato as e:
        return xato(str(e) or "Yuz aniqlanmadi — kameraga toʻgʻri qarang")
    except RuntimeError:
        # Servis oʻchiq — 503, frontend darrov PIN'ga oʻtadi
        return xato("Yuz tanish xizmati ishlamayapti — PIN bilan kiring",
                    status.HTTP_503_SERVICE_UNAVAILABLE)

    if not natija.get("mos"):
        _audit(worker, f"kirish {tabel}", "yuz mos kelmadi",
               f"score={natija.get('score')}")
        return xato("Yuz mos kelmadi — PIN bilan kiring", status.HTTP_401_UNAUTHORIZED)

    if not natija.get("jonli", True):
        _audit(worker, f"kirish {tabel}", "jonlilik tekshiruvidan oʻtmadi")
        return xato("Jonli yuz aniqlanmadi — kameraga toʻgʻridan qarang yoki PIN bilan kiring",
                    status.HTTP_401_UNAUTHORIZED)

    juftlik = tokens.token_juftligi(worker, _agent(request))
    worker.last_login = timezone.now()
    worker.save(update_fields=["last_login"])
    _audit(worker, f"kirish {tabel}", "Face ID bilan kirdi",
           f"score={natija.get('score')}")

    return Response({**juftlik, "user": me_json(worker)})


# ---------------------------------------------------------------------
# Birinchi marta PIN oʻrnatish
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def set_pin(request):
    """
    Faqat PIN'i YOʻQ yoki majburiy almashtirishga qoʻyilgan ishchi
    oʻzi uchun PIN oʻrnata oladi. Mavjud PIN'ni almashtirish bu yerdan
    mumkin emas — buning uchun admin tiklashi kerak.
    """
    tabel = str(request.data.get("tabel", "")).strip()
    pin = str(request.data.get("pin", "")).strip()

    if not valid_pin_format(pin):
        return xato("PIN 4 xonali raqam boʻlishi kerak")

    worker = Worker.objects.filter(tabel=tabel, deleted=False, faol=True).first()
    if not worker:
        return xato("Tabel raqami topilmadi", status.HTTP_404_NOT_FOUND)

    if worker.pin_hash and not worker.pin_reset:
        return xato("PIN allaqachon oʻrnatilgan. Tiklash uchun administratorga murojaat qiling", 409)

    with transaction.atomic():
        worker.set_pin(pin)
        worker.save(update_fields=["pin_hash", "pin_reset"])
        _audit(worker, f"ishchi {worker.tabel}", "PIN oʻrnatildi")

    juftlik = tokens.token_juftligi(worker, _agent(request))
    return Response({"ok": True, **juftlik, "user": me_json(worker)})


# ---------------------------------------------------------------------
# Token yangilash / chiqish
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([AllowAny])
def refresh(request):
    token = str(request.data.get("refresh", "")).strip()
    row = tokens.read_refresh(token)
    if not row:
        return xato("Refresh token yaroqsiz yoki muddati oʻtgan", status.HTTP_401_UNAUTHORIZED)

    worker = row.worker
    if worker.deleted or not worker.faol:
        return xato("Foydalanuvchi faolsiz", status.HTTP_401_UNAUTHORIZED)

    return Response({"access": tokens.make_access(worker)})


@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    tokens.revoke_refresh(str(request.data.get("refresh", "")).strip())
    return Response({"ok": True})


# ---------------------------------------------------------------------
# Joriy foydalanuvchi
# ---------------------------------------------------------------------

@api_view(["GET"])
def me(request):
    return Response(me_json(request.user))


# ---------------------------------------------------------------------
# Oʻz yuzini qoʻshish / yangilash
# ---------------------------------------------------------------------

@api_view(["POST"])
def me_face(request):
    """
    {frames[]} → {ok, faceBor}

    Roʻyxatdan oʻtishda kamera boʻlmagan ishchi keyinroq shu yerdan
    Face ID qoʻshadi. Faqat oʻzining yuzini oʻzgartira oladi.
    """
    kadrlar = kadrlar_ol(request)
    if not kadrlar:
        return xato("Surat yuborilmadi")

    worker = request.user
    try:
        worker.face_vector = face.vektor(kadrlar[0])
    except face.FaceXato as e:
        return xato(str(e) or "Suratda yuz aniqlanmadi — qayta urinib koʻring")
    except RuntimeError:
        return xato("Yuz tanish xizmati ishlamayapti — keyinroq urinib koʻring",
                    status.HTTP_503_SERVICE_UNAVAILABLE)

    worker.face_image = kadrlar[0]
    worker.save(update_fields=["face_vector", "face_image"])
    _audit(worker, f"ishchi {worker.tabel}", "Face ID yangilandi")

    return Response({"ok": True, "faceBor": True})


# ---------------------------------------------------------------------
# Admin: PIN tiklash
# ---------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAdmin])
def reset_pin(request):
    """
    pin berilsa — oʻsha PIN oʻrnatiladi.
    pin berilmasa — PIN oʻchiriladi va ishchi keyingi kirishda oʻzi
    yangisini oʻrnatadi (majburiy almashtirish).
    """
    user_id = request.data.get("userId")
    tabel = str(request.data.get("tabel", "")).strip()
    pin = str(request.data.get("pin", "") or "").strip()

    qs = Worker.objects.filter(deleted=False)
    worker = qs.filter(id=user_id).first() if user_id else qs.filter(tabel=tabel).first()
    if not worker:
        return xato("Ishchi topilmadi", status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        if pin:
            if not valid_pin_format(pin):
                return xato("PIN 4 xonali raqam boʻlishi kerak")
            worker.set_pin(pin)
            rejim = "set"
        else:
            worker.clear_pin()
            rejim = "reset"
        worker.save(update_fields=["pin_hash", "pin_reset"])

        # Eski seanslar bekor qilinadi — eski PIN bilan kirgan qurilma chiqib ketadi
        tokens.revoke_all(worker)
        _audit(request.user, f"ishchi {worker.tabel}", f"PIN {rejim}")

    return Response({"ok": True, "mode": rejim})


# ---------------------------------------------------------------------
# Ishchi surati (FaceID) — alohida endpoint
# ---------------------------------------------------------------------

@api_view(["GET"])
def worker_face(request, worker_id):
    """
    Surat butun holat bilan birga yuborilmaydi (800 ta base64 = juda
    katta javob). Kerak boʻlganda shu endpointdan bittalab olinadi.
    """
    worker = Worker.objects.filter(id=worker_id, deleted=False).only("face_image").first()
    if not worker or not worker.face_image:
        return xato("Surat topilmadi", status.HTTP_404_NOT_FOUND)

    from django.http import HttpResponse

    raw = worker.face_image
    # "data:image/jpeg;base64,...." koʻrinishida saqlanadi
    if raw.startswith("data:"):
        import base64

        header, _, payload = raw.partition(",")
        mime = header.split(";")[0].removeprefix("data:") or "image/jpeg"
        try:
            body = base64.b64decode(payload)
        except Exception:
            return xato("Surat buzilgan", status.HTTP_404_NOT_FOUND)
        javob = HttpResponse(body, content_type=mime)
        javob["Cache-Control"] = "private, max-age=3600"
        return javob

    return xato("Surat formati notanish", status.HTTP_404_NOT_FOUND)
