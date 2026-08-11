"""
=====================================================================
gunicorn sozlamalari.

Gunicorn ishga tushganda joriy papkadagi shu faylni avtomatik oʻqiydi,
shuning uchun ishga tushirish buyrugʻi oddiy boʻlib qoladi:

    gunicorn config.wsgi:application

Nega shunday: Railway/Fly kabi platformalar portni PORT muhit
oʻzgaruvchisida beradi va ishga tushirish buyrugʻini exec shaklida
(shellsiz) uzatadi. Buyruq ichida "--bind 0.0.0.0:$PORT" yozilsa,
$PORT kengaymaydi va gunicorn "'$PORT' is not a valid port number"
xatosi bilan toʻxtaydi. Portni shu yerda — Python tomonida — oʻqisak,
buyruqda umuman oʻzgaruvchi qolmaydi va muammo tugʻilmaydi.
=====================================================================
"""

import os


def _son(kalit: str, zaxira: int) -> int:
    """Muhit oʻzgaruvchisini butun songa oʻgiradi; boʻsh/notoʻgʻri boʻlsa zaxira."""
    try:
        return int(os.environ.get(kalit, "").strip() or zaxira)
    except ValueError:
        return zaxira


# Platforma bergan port, boʻlmasa 8000 (docker-compose va lokal ishlash)
bind = f"0.0.0.0:{os.environ.get('PORT', '').strip() or '8000'}"

# Xotira cheklangan tariflarda har bir worker ~150 MB yeydi — 2 ta xavfsiz.
# Yuklama ortsa WEB_CONCURRENCY orqali koʻtariladi.
workers = _son("WEB_CONCURRENCY", 2)
threads = _son("GUNICORN_THREADS", 4)

# FaceID surati base64 holida keladi — sekin soʻrovlar uchun bardoshli timeout
timeout = _son("GUNICORN_TIMEOUT", 120)
graceful_timeout = 30
keepalive = 5

# Loglar konteyner chiqishiga — platforma loglarida koʻrinadi
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info").strip() or "info"
