"""
=====================================================================
Qurilmani tanish — telefonmi yoki kompyutermi.

Nima uchun muhim: ishchi oʻz telefonidan bir marta kirgach, keyingi
safar PIN qayta soʻralmasligi kerak. Depodagi kompyuter esa UMUMIY —
undan 4-5 kishi kiradi, shuning uchun u yerda har safar tabel + PIN
soʻralishi shart. Bu ikkisini ajratmasak, bir ishchi kompyuterni ochib
boshqasining kabinetiga tushib qolardi.

Xulosa UCH manbadan yigʻiladi:

  1. Sec-CH-UA-Mobile: ?1  — Chromium brauzerlar buni HAR soʻrovda
                             avtomatik yuboradi (Android Chrome, Edge).
                             Eng ishonchli signal.
  2. X-Qurilma-Tur         — mijozning oʻz xulosasi: sensorli ekran,
                             `pointer: coarse`, navigator.userAgentData.
                             iPad uchun SHART — iPadOS Safari oʻzini
                             standart holatda kompyuter deb tanishtiradi.
  3. User-Agent matni      — Safari/Firefox uchun zaxira.

MUHIM QOIDA: mijozga yolgʻiz ishonilmaydi. Agar u «men telefonman» deb
yolgʻon aytsa, umumiy kompyuterda seans ochiq qolib ketardi. Shuning
uchun server User-Agent'ni MUSTAQIL tekshiradi va qurilma faqat
IKKALASI ham roziligida mobil deb tan olinadi.

Aniqlash xato ishlagan taqdirda ham natija xavfsiz tomonga ogʻadi:
noaniq holatda qurilma «kompyuter» hisoblanadi, yaʼni PIN soʻraladi.
=====================================================================
"""

from __future__ import annotations

import re

from django.utils import timezone

from core.models import Qurilma, RefreshToken, Worker

# Telefon belgilari. `mobile safari` — iPhone/iPad Safari; oddiy
# `safari` emas, chunki uni kompyuter Safari'si ham yozadi.
MOBIL_UA = re.compile(
    r"android|iphone|ipod|iemobile|blackberry|opera mini|mobile safari|windows phone",
    re.I,
)

# Planshetlar. Ular ham «mobil» hisoblanadi — shaxsiy qurilma.
PLANSHET_UA = re.compile(r"ipad|tablet|silk|kindle|playbook", re.I)


# ---------------------------------------------------------------------
# Soʻrovdan xom maʼlumot olish
# ---------------------------------------------------------------------

def _ua(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:255]


def _ip(request) -> str | None:
    """
    Haqiqiy IP. Caddy orqali kelganda `X-Forwarded-For` da bir nechta
    manzil boʻladi — birinchisi mijozniki.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        ip = xff.split(",")[0].strip()
        if ip:
            return ip[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45] or None


def _sarlavha(request, nom: str) -> str:
    return (request.META.get(nom, "") or "").strip()


# ---------------------------------------------------------------------
# Mobilmi — uch signalni birlashtirish
# ---------------------------------------------------------------------

def _sec_ch_mobil(request) -> bool | None:
    """
    `Sec-CH-UA-Mobile` sarlavhasi: "?1" — telefon, "?0" — kompyuter.
    Yuborilmagan boʻlsa None (Safari, Firefox buni yubormaydi).
    """
    xom = _sarlavha(request, "HTTP_SEC_CH_UA_MOBILE")
    if xom == "?1":
        return True
    if xom == "?0":
        return False
    return None


def _mijoz_mobil(request) -> bool | None:
    """Mijozning oʻz xulosasi: `X-Qurilma-Tur: mobil` yoki `kompyuter`."""
    xom = _sarlavha(request, "HTTP_X_QURILMA_TUR").lower()
    if xom == "mobil":
        return True
    if xom == "kompyuter":
        return False
    return None


def _server_mobil(request) -> bool:
    """Serverning mustaqil xulosasi — mijozdan kelgan gapga qaramasdan."""
    ua = _ua(request)
    sec = _sec_ch_mobil(request)
    if sec is not None:
        # Chromium aniq aytdi. Planshet UA'si boʻlsa uni ham qoʻshib olamiz:
        # Android planshetda `Sec-CH-UA-Mobile: ?0` kelishi mumkin.
        return sec or bool(PLANSHET_UA.search(ua))
    return bool(MOBIL_UA.search(ua) or PLANSHET_UA.search(ua))


def mobilmi(request) -> bool:
    """
    Yakuniy qaror. Mijoz ham, server ham «telefon» desagina True.

    Mijoz eski (sarlavha yubormaydi) boʻlsa faqat serverga tayanamiz —
    Flutter ilovasi va eski brauzerlar shu yoʻldan oʻtadi.
    """
    mijoz = _mijoz_mobil(request)
    server = _server_mobil(request)
    if mijoz is None:
        return server
    return bool(mijoz and server)


# ---------------------------------------------------------------------
# Qurilma nomi — foydalanuvchi roʻyxatda tanib olishi uchun
# ---------------------------------------------------------------------

def _nom_ua_dan(ua: str) -> str:
    """User-Agent'dan «Android · Chrome» koʻrinishidagi nom yasaydi."""
    tizim = "Qurilma"
    for kalit, atama in (
        ("android", "Android"),
        ("iphone", "iPhone"),
        ("ipad", "iPad"),
        ("windows", "Windows"),
        ("mac os", "Mac"),
        ("macintosh", "Mac"),
        ("linux", "Linux"),
    ):
        if kalit in ua.lower():
            tizim = atama
            break

    brauzer = ""
    past = ua.lower()
    # Tartib muhim: Edge va Opera oʻzini Chrome deb ham atashadi.
    for kalit, atama in (
        ("edg/", "Edge"),
        ("opr/", "Opera"),
        ("samsungbrowser", "Samsung Browser"),
        ("firefox", "Firefox"),
        ("chrome", "Chrome"),
        ("safari", "Safari"),
    ):
        if kalit in past:
            brauzer = atama
            break

    return f"{tizim} · {brauzer}" if brauzer else tizim


def qurilma_nomi(request) -> str:
    """Mijoz yuborgan nom, boʻlmasa User-Agent'dan yasaladi."""
    nom = _sarlavha(request, "HTTP_X_QURILMA_NOM")[:120]
    return nom or _nom_ua_dan(_ua(request))


# ---------------------------------------------------------------------
# Qurilmani yozib qoʻyish
# ---------------------------------------------------------------------

def qurilma_id(request) -> str:
    """Mijoz yaratgan barqaror UUID. Boʻlmasa boʻsh satr."""
    return _sarlavha(request, "HTTP_X_QURILMA_ID")[:64]


def qurilma_yoz(request, worker: Worker, *, eslab_qol: bool = True) -> Qurilma | None:
    """
    Kirish paytida chaqiriladi: qurilmani topadi yoki yaratadi.

    `eslab_qol=False` — foydalanuvchi «Bu qurilmani eslab qolma» deganda.
    Kompyuter esa hech qachon ishonchli boʻlmaydi, tanlovdan qatʼi nazar.

    Mijoz qurilma id yubormasa (eski versiya, Flutter) None qaytadi —
    tizim eskicha ishlayveradi, hech nima buzilmaydi.
    """
    qid = qurilma_id(request)
    if not qid:
        return None

    mobil = mobilmi(request)
    qurilma, _ = Qurilma.objects.get_or_create(
        worker=worker,
        qurilma_id=qid,
        defaults={"nom": qurilma_nomi(request)},
    )

    qurilma.nom = qurilma.nom or qurilma_nomi(request)
    qurilma.mobil = mobil
    # Faqat telefon ishonchli boʻla oladi — umumiy kompyuterda seans
    # ochiq qolmasligi uchun.
    qurilma.ishonchli = bool(mobil and eslab_qol)
    qurilma.revoked = False
    qurilma.user_agent = _ua(request)
    qurilma.oxirgi_ip = _ip(request)
    qurilma.oxirgi_kirish = timezone.now()
    qurilma.save(update_fields=[
        "nom", "mobil", "ishonchli", "revoked",
        "user_agent", "oxirgi_ip", "oxirgi_kirish",
    ])
    return qurilma


def qurilma_bekor(qurilma: Qurilma) -> None:
    """
    Qurilmani oʻchirish — telefon yoʻqolganda. Uning barcha tokenlari
    bekor qilinadi, yaʼni oʻsha telefon shu zahoti tizimdan chiqadi.
    """
    qurilma.revoked = True
    qurilma.ishonchli = False
    qurilma.save(update_fields=["revoked", "ishonchli"])
    RefreshToken.objects.filter(qurilma=qurilma).update(
        revoked=True, almashtirilgan=False
    )


def qurilma_json(q: Qurilma, joriy_id: str = "") -> dict:
    """«Qurilmalarim» roʻyxati uchun."""
    return {
        "id": str(q.id),
        "nom": q.nom,
        "mobil": q.mobil,
        "ishonchli": q.ishonchli,
        "joriy": bool(joriy_id) and q.qurilma_id == joriy_id,
        "oxirgiKirish": q.oxirgi_kirish.isoformat(),
        "oxirgiIp": q.oxirgi_ip or "",
    }
