"""
=====================================================================
ID-karta imzolarini yagona tizimga import qilish.

    python manage.py import_imzolar --csv "C:\\...\\imzolar_royxati.csv"
    python manage.py import_imzolar --csv imzolar_royxati.csv --quruq

Manba — depo-id chiqargan roʻyxat (imzolar_royxati.csv):
    TABEL_RAQAMI;FIO;LAVOZIM;BOLIM;IMZO_HMAC16

Har bir qator uchun:
  • tabel boʻyicha Worker topiladi (topilmasa — oʻtkazib yuboriladi);
  • unga `Signature(doc_type="card_id")` yaratiladi/yangilanadi —
    hash = depo-id niki (IMZO_HMAC16) boʻyicha saqlanadi, shu sabab
    ALLAQACHON CHOP ETILGAN kartalar oʻzgarishsiz haqiqiy boʻlib qoladi;
  • `Worker.imzo_id` shu imzoga bogʻlanadi.

Idempotent: qayta ishga tushirsa, mavjud karta imzosi yangilanadi,
takrorlanmaydi. PIN/rol/soft-delete ga TEGMAYDI.
=====================================================================
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import imzo
from core.models import Signature, Worker

DATA = Path(__file__).resolve().parent.parent.parent / "data"


def _fio_norm(s: str) -> str:
    """Solishtirish uchun FIO ni soddalashtiradi (registr/oʻ/gʻ/probel)."""
    s = (s or "").lower().replace("ʻ", "").replace("'", "").replace("`", "")
    s = s.replace("o‘", "o").replace("g‘", "g").replace("’", "")
    return " ".join(s.split())


def _oqi(csv_path: Path):
    """CSV ni ustun nomlaridan qatʼi nazar oʻqiydi (BOM va ; ajratgich)."""
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)
    if not rows:
        return []
    head = [h.strip().upper() for h in rows[0]]

    def idx(*names, default=None):
        for n in names:
            if n in head:
                return head.index(n)
        return default

    it = idx("TABEL_RAQAMI", "TABEL", "ID")
    ifio = idx("FIO", "F.I.SH", "FISH")
    ilav = idx("LAVOZIM", "POSITION")
    ibol = idx("BOLIM", "BO'LIM", "DEPARTMENT")
    iimzo = idx("IMZO_HMAC16", "IMZO", "HMAC")
    if it is None or iimzo is None:
        raise CommandError("CSV da TABEL_RAQAMI yoki IMZO_HMAC16 ustuni topilmadi")

    out = []
    for r in rows[1:]:
        if not r or len(r) <= max(it, iimzo):
            continue
        out.append({
            "tabel": r[it].strip(),
            "fio": (r[ifio].strip() if ifio is not None and len(r) > ifio else ""),
            "lavozim": (r[ilav].strip() if ilav is not None and len(r) > ilav else ""),
            "bolim": (r[ibol].strip() if ibol is not None and len(r) > ibol else ""),
            "imzo": r[iimzo].strip().upper(),
        })
    return out


class Command(BaseCommand):
    help = "ID-karta imzolarini (IMZO_HMAC16) yagona Signature tizimiga import qiladi"

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(DATA / "imzolar_royxati.csv"),
                            help="imzolar_royxati.csv fayl yoʻli")
        parser.add_argument("--quruq", action="store_true",
                            help="Bazaga yozmasdan faqat koʻrsatadi")

    @transaction.atomic
    def handle(self, *args, **o):
        csv_path = Path(o["csv"])
        if not csv_path.exists():
            raise CommandError(f"CSV topilmadi: {csv_path}")

        rows = _oqi(csv_path)
        quruq = o["quruq"]
        yangi = yangilangan = topilmadi = fio_ogoh = 0

        for r in rows:
            # 1) toʻliq tabel boʻyicha; 2) boʻlmasa oxirgi-4-raqam boʻyicha
            w = Worker.objects.filter(tabel=r["tabel"]).first()
            if not w:
                t4 = imzo.tabel4(r["tabel"])
                w = Worker.objects.filter(tabel=t4).first() if t4 else None
            if not w:
                topilmadi += 1
                continue

            # Kolliziya himoyasi: oxirgi-4-raqam bir xil boʻlgan ikki xil
            # kartani ajratish uchun FIO ni solishtiramiz. Mos kelmasa —
            # ogohlantiramiz, lekin importni davom ettiramiz (birinchi mos
            # tabel olinadi); nomuvofiqlikni foydalanuvchi koʻradi.
            if r["fio"] and _fio_norm(r["fio"]) != _fio_norm(w.fio):
                fio_ogoh += 1
                self.stdout.write(self.style.WARNING(
                    f"  FIO mos emas: karta {r['tabel']} ({r['fio'][:28]}) "
                    f"→ tabel {w.tabel} ({w.fio[:28]})"
                ))
            if quruq:
                self.stdout.write(f"  {r['tabel']:<14} {r['imzo']}  {r['fio'][:30]}")
                continue

            payload = {
                "fio": r["fio"] or w.fio,
                "lavozim": r["lavozim"] or (w.position.nomi if w.position else ""),
                "tabel": r["tabel"],
                "bolim": r["bolim"],
            }
            sig = Signature.objects.filter(doc_type="card_id", doc_id=str(w.id)).first()
            if sig:
                sig.hash = r["imzo"]
                sig.field = "id"
                sig.payload = payload
                sig.bekor = False
                sig.save(update_fields=["hash", "field", "payload", "bekor"])
                yangilangan += 1
            else:
                sig = Signature.objects.create(
                    doc_type="card_id", doc_id=str(w.id), field="id",
                    user=w, hash=r["imzo"], payload=payload,
                )
                yangi += 1

            if w.imzo_id != str(sig.id):
                w.imzo_id = str(sig.id)
                w.save(update_fields=["imzo_id"])

        self.stdout.write(self.style.SUCCESS(
            f"\nImport tugadi: {yangi} yangi, {yangilangan} yangilangan, "
            f"{topilmadi} tabel bazada topilmadi, {fio_ogoh} FIO nomuvofiq "
            f"(jami {len(rows)} qator)."
        ))
