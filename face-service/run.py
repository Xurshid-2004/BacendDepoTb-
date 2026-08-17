"""
=====================================================================
Face servisini ishga tushirish nuqtasi.

Nega alohida fayl: Railway/Fly kabi platformalar portni PORT muhit
oʻzgaruvchisida beradi va ishga tushirish buyrugʻini exec shaklida
(shellsiz) uzatishi mumkin. Buyruq ichida "--port $PORT" yozilsa,
oʻzgaruvchi kengaymaydi va uvicorn "'$PORT' is not a valid integer"
xatosi bilan toʻxtaydi. Portni shu yerda — Python tomonida — oʻqisak,
buyruqda umuman oʻzgaruvchi qolmaydi.

Bu Bacend/gunicorn.conf.py dagi yondashuvning aynan oʻzi.
=====================================================================
"""

import os

import uvicorn


def _son(kalit: str, zaxira: int) -> int:
    """Muhit oʻzgaruvchisini butun songa oʻgiradi; boʻsh/notoʻgʻri boʻlsa zaxira."""
    try:
        return int(os.environ.get(kalit, "").strip() or zaxira)
    except ValueError:
        return zaxira


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        # "::" — Railway'ning ichki tarmogʻi (*.railway.internal) IPv6 da
        # ishlaydi, 0.0.0.0 esa faqat IPv4 ni tinglaydi va Django ulana
        # olmaydi. Linux'da "::" ikkala oilani ham qabul qiladi, shuning
        # uchun public domen ham shu bilan ishlayveradi.
        host=os.environ.get("HOST", "").strip() or "::",
        port=_son("PORT", 8000),
        # Bitta worker: har biri buffalo_l modelini alohida xotiraga
        # yuklaydi (~1.2 GB). Ikkitasi xotira limitidan chiqarib yuboradi.
        workers=_son("WEB_CONCURRENCY", 1),
        log_level=os.environ.get("LOG_LEVEL", "").strip() or "info",
    )
