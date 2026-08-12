"""
=====================================================================
Depo xodimlarini bazaga yozish (kadrlar roʻyxati).

    python manage.py import_xodimlar              # qoʻshadi + yangilaydi
    python manage.py import_xodimlar --rasmsiz    # suratlarsiz (tezroq)
    python manage.py import_xodimlar --quruq      # faqat koʻrsatadi, yozmaydi

Manba: core/data/xodimlar.json va core/data/rasmlar/<tabel>.jpg
(«Xodimlar tabel raqamlari jadvali» — SPA + Taʼmirlash sexi papkalari).

Buyruq qayta-qayta ishga tushirilishi mumkin: mavjud tabel raqami
YANGILANADI, takrorlanmaydi.

MUHIM: bu buyruq PIN'ga TEGMAYDI. Xodim birinchi marta kirganda oʻzi
PIN yaratadi (tabel → «PIN oʻrnating» → keyingi kirishlarda tabel+PIN).
Roʻyxatdan oʻtgan xodimning roli ham qayta yozilmaydi.
=====================================================================
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from core.logic import today
from core.models import Card, Depo, Position, Talon, Worker

DATA = Path(__file__).resolve().parent.parent.parent / "data"
JSON_FAYL = DATA / "xodimlar.json"
RASM_PAPKA = DATA / "rasmlar"

# Lavozim nomidagi kalit soʻz → rol. Roʻyxatda yoʻq lavozim — «ishchi».
ROL_QOIDA: list[tuple[str, str]] = [
    ("depo boshlig", "depo_boshligi"),
    ("boshliq o", "depo_boshligi"),          # boshliq oʻrinbosari
    ("bosh muhandis", "depo_boshligi"),
    ("bosh hisobchi", "bosh_xisobchi"),
    ("mehnat muhofazasi va texnika xavfsizligi", "tb_xodim"),
    ("mashinist yo", "yoriqchi"),            # mashinist yoʻriqchisi
    ("omborchi", "ombor_mudiri"),
    ("katta usta", "sex_boshligi"),
    ("sex boshlig", "sex_boshligi"),
    ("buxgalter", "bugalter"),
    ("hisob-kitob buxgalteri", "bugalter"),
]


def rol_top(lavozim: str) -> str:
    l = lavozim.lower()
    for kalit, rol in ROL_QOIDA:
        if kalit in l:
            return rol
    return "ishchi"


class Command(BaseCommand):
    help = "Depo xodimlarini (296 ta) rasm va lavozimi bilan bazaga yozadi"

    def add_arguments(self, parser):
        parser.add_argument("--rasmsiz", action="store_true", help="Suratlarni yozmaslik")
        parser.add_argument("--quruq", action="store_true", help="Bazaga yozmasdan koʻrsatish")

    @transaction.atomic
    def handle(self, *args, **o):
        if not JSON_FAYL.exists():
            self.stderr.write(f"Maʼlumot fayli topilmadi: {JSON_FAYL}")
            return

        rows = json.loads(JSON_FAYL.read_text(encoding="utf-8"))
        depo = Depo.joriy()
        self.stdout.write(f"Manba: {len(rows)} ta xodim · depo: {depo.nomi}")

        # --- lavozimlar ---
        # Tartib raqami mavjudlaridan keyin davom etadi
        oxirgi = Position.objects.filter(depo=depo).order_by("-tartib").first()
        keyingi = (oxirgi.tartib if oxirgi else 0) + 1
        pos_map: dict[str, Position] = {}
        yangi_pos = 0
        for nomi in sorted({r["lavozim"] for r in rows if r["lavozim"]}):
            p = Position.objects.filter(depo=depo, nomi=nomi).first()
            if not p and not o["quruq"]:
                p = Position.objects.create(depo=depo, nomi=nomi, tartib=keyingi)
                keyingi += 1
                yangi_pos += 1
            if p:
                pos_map[nomi] = p

        qoshildi = yangilandi = rasmli = 0
        for r in rows:
            tabel = str(r["tabel"]).strip()
            if not tabel:
                continue

            rasm = ""
            if not o["rasmsiz"] and r.get("rasm"):
                fayl = RASM_PAPKA / r["rasm"]
                if fayl.exists():
                    b64 = base64.b64encode(fayl.read_bytes()).decode()
                    rasm = f"data:image/jpeg;base64,{b64}"
                    rasmli += 1

            position = pos_map.get(r["lavozim"])
            w = Worker.objects.filter(tabel=tabel).first()

            if o["quruq"]:
                self.stdout.write(
                    f"  {tabel} {r['familiya']} {r['ism']} — {r['lavozim']} "
                    f"[{rol_top(r['lavozim'])}]{' · rasm' if rasm else ''}"
                    f"{' · MAVJUD' if w else ''}"
                )
                continue

            if w:
                # Mavjud xodim — kadrlar maʼlumoti yangilanadi.
                # Rol faqat hali oʻzgartirilmagan boʻlsa qoʻyiladi:
                # admin qoʻlda bergan huquq import bilan yoʻqolmasin.
                w.familiya = r["familiya"] or w.familiya
                w.ism = r["ism"] or w.ism
                w.otasi = r["otasi"]
                w.sex = r["sex"]
                w.ish_joyi = r["lavozimToliq"]
                w.jinsi = r["jinsi"]
                if position:
                    w.position = position
                if rasm:
                    w.rasm = rasm
                if not w.roles:
                    w.roles = [rol_top(r["lavozim"])]
                w.save()
                if position:
                    w.positions.set([position])
                yangilandi += 1
                continue

            w = Worker.objects.create(
                depo=depo,
                tabel=tabel,
                familiya=r["familiya"],
                ism=r["ism"],
                otasi=r["otasi"],
                position=position,
                sex=r["sex"],
                ish_joyi=r["lavozimToliq"],
                kirgan_sana=today(),
                jinsi=r["jinsi"],
                roles=[rol_top(r["lavozim"])],
                faol=True,
                rasm=rasm,
            )
            w.set_unusable_password()          # kirish faqat PIN orqali
            w.save(update_fields=["password"])
            if position:
                w.positions.set([position])

            Card.objects.get_or_create(worker=w, defaults={"ochilgan": today()})
            for n in (1, 2, 3):
                Talon.objects.get_or_create(worker=w, raqam=n, defaults={"olingan": False})
            qoshildi += 1

        if o["quruq"]:
            self.stdout.write(self.style.WARNING("Quruq rejim — bazaga hech narsa yozilmadi"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: {qoshildi} ta yangi, {yangilandi} ta yangilandi · "
            f"{rasmli} ta rasm · {yangi_pos} ta yangi lavozim"
        ))
        self.stdout.write(
            f"Bazada jami: {Worker.objects.filter(deleted=False).count()} ishchi, "
            f"{Position.objects.count()} lavozim"
        )
        self.stdout.write(
            "Xodimlar hali PIN yaratmagan — birinchi kirishda tabel raqamini "
            "terib, oʻzlari PIN oʻrnatadi."
        )
