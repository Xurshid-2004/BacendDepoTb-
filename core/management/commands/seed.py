"""
=====================================================================
Boshlangʻich maʼlumotni bazaga yozish.

    python manage.py seed              # normativ maʼlumot (31-ilova)
    python manage.py seed --demo       # + namunaviy ishchilar/arizalar
    python manage.py seed --admin 10001 --pin 1234

Normativ qism (lavozimlar, buyumlar, normalar) — HAQIQIY maʼlumot,
lib/seed.ts dan aynan koʻchirilgan. Demo qismi esa faqat sinov uchun.

Buyruq qayta-qayta ishga tushirilishi mumkin: mavjud yozuvlar
yangilanadi, takrorlanmaydi (get_or_create / update_or_create).
=====================================================================
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.logic import add_months, today
from core.models import (
    Card, Depo, Exam, Item, Line, Norm, Position, Stock, Talon, Unit, Worker,
)

# ---------------------------------------------------------------------
# Buyumlar — [kalit, nomi, birlik, qishkimi, narx]
# ---------------------------------------------------------------------

ITEMS: list[tuple[str, str, str, bool, int]] = [
    ("kostyum_xb", "Kostyum x/b", "dona", False, 420000),
    ("kostyum_paxta", "Paxta tolali kostyum", "dona", False, 465000),
    ("xalat_paxta", "Paxta tolali xalat", "dona", False, 310000),
    ("kostyum_payvand", "Payvandchi kostyumi", "dona", False, 640000),
    ("qolqob_qurama", "Qurama qoʻlqob", "juft", False, 18000),
    ("qolqob_brezent", "Brezent qoʻlqob", "juft", False, 26000),
    ("qolqop_rezina", "Rezina qoʻlqop", "juft", False, 32000),
    ("qolqop_dielektrik", "Dielektrik qoʻlqop", "juft", False, 145000),
    ("qolqob_maxsus", "Maxsus qoʻlqob (vibratsiyaga qarshi)", "juft", False, 88000),
    ("botinka_charm", "Charm botinka", "juft", False, 520000),
    ("etik_kirza", "Kirza etik", "juft", False, 390000),
    ("kozoynak", "Himoya koʻzoynagi", "dona", False, 54000),
    ("respirator", "Respirator", "dona", False, 22000),
    ("kaska", "Himoya kaskasi", "dona", False, 96000),
    ("quloqchin", "Shovqinga qarshi quloqchin", "dona", False, 74000),
    ("kurtka_gudok", "Issiq kurtka «Gudok»", "dona", True, 890000),
    ("kostyum_issiq", "Issiq kostyum (kurtka)", "dona", True, 810000),
    ("etik_issiq", "Issiq etik", "juft", True, 610000),
    ("etik_yufta", "Issiq yufta etik", "juft", True, 660000),
]

# ---------------------------------------------------------------------
# Normalar — takrorlanuvchi toʻplamlar
# ---------------------------------------------------------------------

BASE_CHILANGAR = [
    ("kostyum_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12),
    ("respirator", None), ("kozoynak", None), ("kaska", None),
]
QISH_CHILANGAR = [("kostyum_issiq", 36), ("etik_yufta", 24)]

BASE_PAYVAND = [
    ("kostyum_payvand", 12), ("qolqob_brezent", 1),
    ("botinka_charm", 18), ("kozoynak", None),
]
QISH_PAYVAND = [("kostyum_issiq", 24), ("etik_yufta", 24)]

BASE_UNIVERSAL = [("kostyum_paxta", 12), ("botinka_charm", 24), ("qolqob_qurama", 2)]
QISH_UNIVERSAL = [("kostyum_issiq", 36)]

# ---------------------------------------------------------------------
# 31-ILOVA: lavozim → norma
# ---------------------------------------------------------------------

POSITIONS: list[tuple[str, list, list]] = [
    ("Teplovoz mashinisti va yordamchisi",
     [("kostyum_xb", 12), ("qolqob_qurama", 2), ("kozoynak", None), ("botinka_charm", 24)],
     [("kurtka_gudok", 36), ("etik_issiq", 24)]),
    ("Elektrovoz mashinisti va yordamchisi",
     [("kostyum_xb", 12), ("qolqob_qurama", 2), ("kozoynak", None), ("botinka_charm", 24)],
     [("kurtka_gudok", 36), ("etik_issiq", 24)]),
    ("Depo navbatchisi",
     [("kostyum_xb", 12), ("botinka_charm", 12)],
     [("kurtka_gudok", 36), ("etik_issiq", 24)]),
    ("Taʼmirlash sexi farroshi",
     [("kostyum_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12), ("qolqop_rezina", None)],
     [("kostyum_issiq", 36)]),
    ("Tayyorlov sexi chilangari", BASE_CHILANGAR, QISH_CHILANGAR),
    ("Akkumulyatorchi", BASE_CHILANGAR, QISH_CHILANGAR),
    ("Gaz va elektr payvandchisi", BASE_PAYVAND, QISH_PAYVAND),
    ("PTO sexi chilangari", BASE_CHILANGAR, QISH_CHILANGAR),
    ("Omborxona mudiri",
     [("xalat_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 24)],
     [("kostyum_issiq", 36)]),
    ("Dush va maʼmuriy bino farroshi",
     [("xalat_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12), ("qolqop_rezina", None)],
     []),
    ("Taʼmirlash sexi chilangari", BASE_CHILANGAR, QISH_CHILANGAR),
    ("Maʼmuriy bino farroshi",
     [("xalat_paxta", 12), ("botinka_charm", 12), ("qolqop_rezina", None)], []),
    ("Kimyo laboratoriyasi ishchisi",
     [("xalat_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12), ("qolqop_rezina", None)],
     []),
    ("Temirchi",
     [("kostyum_paxta", 24), ("qolqob_brezent", 1), ("botinka_charm", 12),
      ("kozoynak", None), ("quloqchin", None)],
     []),
    ("Suvoqchi-boʻyoqchi", BASE_CHILANGAR, [("kostyum_issiq", 36)]),
    ("Qozonxona gaz va elektr payvandchisi", BASE_PAYVAND, QISH_PAYVAND),
    ("Qozonxona mashinisti", BASE_UNIVERSAL, QISH_UNIVERSAL),
    ("Akfachi", BASE_UNIVERSAL, QISH_UNIVERSAL),
    ("Duradgor", BASE_UNIVERSAL, QISH_UNIVERSAL),
    ("Betonchi va gʻisht teruvchi",
     [("kostyum_paxta", 12), ("qolqob_qurama", 1), ("etik_kirza", 12), ("qolqob_maxsus", 2)],
     [("kostyum_issiq", 36)]),
    ("Haydovchi",
     [("kostyum_paxta", 12), ("etik_kirza", 24), ("qolqob_qurama", 2)], QISH_UNIVERSAL),
    ("Traktorchi", BASE_UNIVERSAL, QISH_UNIVERSAL),
    ("Qorovul",
     [("kostyum_paxta", 24), ("botinka_charm", 24)], [("kurtka_gudok", 36)]),
    ("Yongʻin xavfsizligi chilangari", BASE_UNIVERSAL, QISH_UNIVERSAL),
    ("Tokar",
     [("kostyum_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12),
      ("kozoynak", None), ("kaska", None)],
     [("kostyum_issiq", 36)]),
    ("Taʼmirlash sexi katta ustasi",
     [("kostyum_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12)],
     [("kostyum_issiq", 36)]),
    ("Reostat sexi katta ustasi",
     [("kostyum_paxta", 12), ("qolqob_qurama", 2), ("botinka_charm", 12),
      ("qolqop_dielektrik", None)],
     [("kostyum_issiq", 36)]),
    ("Mehnat muhofazasi muhandisi",
     [("kostyum_paxta", 12), ("botinka_charm", 12)],
     [("kostyum_issiq", 36), ("etik_yufta", 24)]),
]

UNITS = ["dona", "juft", "kg", "metr", "sm"]

LINES = [
    "Buxoro — Qorakoʻl", "Buxoro — Navoiy", "Buxoro-1 stansiyasi",
    "Qiziltepa — Buxoro", "Kogon stansiyasi", "Buxoro — Olot",
]

# Namunaviy xodimlar — faqat --demo bilan
DEMO_STAFF = [
    ("10001", "Abduvaliyev", "Ohun", "Olimjon oʻgʻli", ["admin", "tb_xodim"], 28),
    ("10440", "Sattorov", "Rustam", "Anvarovich", ["depo_boshligi"], 28),
    ("10478", "Islomov", "Dilshod", "Salimovich", ["bosh_xisobchi"], 28),
    ("10517", "Nazarova", "Malika", "Anvarovna", ["bugalter"], 28),
    ("10557", "Ergashev", "Ulugʻbek", "Zokirovich", ["tb_xodim"], 28),
    ("10598", "Xolmatov", "Bekzod", "Rustamovich", ["ombor_mudiri"], 9),
    ("10640", "Turdiyev", "Akmal", "Baxodirovich", ["sex_boshligi"], 26),
    ("10683", "Umarov", "Farrux", "Alisherovich", ["yoriqchi"], 2),
    ("10727", "Qurbonov", "Nodir", "Rustamovich", ["yoriqchi"], 1),
]


class Command(BaseCommand):
    help = "Boshlangʻich (normativ) maʼlumotni bazaga yozadi"

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true",
                            help="Namunaviy xodimlarni ham qoʻshish")
        parser.add_argument("--admin", type=str, default="",
                            help="Administrator tabel raqami")
        parser.add_argument("--fio", type=str, default="",
                            help='Administrator F.I.Sh. — "Familiya Ism Otasi"')
        parser.add_argument("--pin", type=str, default="",
                            help="Boshlangʻich PIN (4 raqam). Berilmasa — ishchi "
                                 "birinchi kirishda oʻzi oʻrnatadi (xavfsizroq)")
        parser.add_argument("--stock", type=int, default=0,
                            help="Har bir buyum uchun boshlangʻich ombor qoldigʻi")

    @transaction.atomic
    def handle(self, *args, **o):
        self.stdout.write(self.style.MIGRATE_HEADING("TB tizimi — boshlangʻich maʼlumot"))

        # --- depo ---
        # Depo.joriy() topilmasa vaqtinchalik nom bilan yaratadi
        # ("TCH-6 lokomotiv deposi"). Shu holatdagina haqiqiy nomga
        # almashtiramiz — admin qoʻlda oʻzgartirgan nomni buzmaymiz.
        depo = Depo.joriy()
        vaqtinchalik = f"{depo.kod} lokomotiv deposi"

        yangilash = {}
        if not depo.nomi or depo.nomi == vaqtinchalik:
            yangilash["nomi"] = "Buxoro lokomotiv deposi"
        if not depo.tashkilot:
            yangilash["tashkilot"] = '"TEMIRYOʻLINFRATUZILMA" AJ'

        if yangilash:
            Depo.objects.filter(pk=depo.pk).update(**yangilash)
            depo.refresh_from_db()

        self.stdout.write(f"  Depo: {depo.kod} — {depo.nomi}")

        # --- birliklar / liniyalar ---
        for i, u in enumerate(UNITS):
            Unit.objects.get_or_create(nomi=u, defaults={"tartib": i + 1})
        for i, l in enumerate(LINES):
            Line.objects.get_or_create(nomi=l, defaults={"tartib": i + 1})
        self.stdout.write(f"  Birliklar: {Unit.objects.count()} · Liniyalar: {Line.objects.count()}")

        # --- buyumlar ---
        item_map: dict[str, Item] = {}
        for i, (kalit, nomi, unit, qishki, narx) in enumerate(ITEMS):
            item, _ = Item.objects.update_or_create(
                nomi=nomi,
                defaults={
                    "kod": f"{10 + i:02d}-{str(1000 + i * 7)[:4]}",
                    "unit": unit,
                    "qishki": qishki,
                    "narx": narx,
                },
            )
            item_map[kalit] = item
            Stock.objects.get_or_create(item=item, defaults={"qoldiq": o["stock"]})
        self.stdout.write(f"  Buyumlar: {Item.objects.count()}")

        # --- lavozimlar va normalar ---
        norma_soni = 0
        pos_map: dict[int, Position] = {}
        for idx, (nomi, base, qish) in enumerate(POSITIONS, start=1):
            position, _ = Position.objects.update_or_create(
                depo=depo, nomi=nomi, defaults={"tartib": idx},
            )
            pos_map[idx] = position

            for kalit, muddat in base:
                Norm.objects.update_or_create(
                    position=position, item=item_map[kalit],
                    defaults={"muddat_oy": muddat, "qishki": False},
                )
                norma_soni += 1
            for kalit, muddat in qish:
                Norm.objects.update_or_create(
                    position=position, item=item_map[kalit],
                    defaults={"muddat_oy": muddat, "qishki": True},
                )
                norma_soni += 1

        self.stdout.write(
            f"  Lavozimlar: {Position.objects.count()} · Normalar: {Norm.objects.count()}"
        )

        # --- namunaviy xodimlar ---
        if o["demo"]:
            qoshildi = 0
            for tabel, fam, ism, ota, roles, pos_idx in DEMO_STAFF:
                if Worker.objects.filter(tabel=tabel).exists():
                    continue
                w = Worker.objects.create(
                    depo=depo, tabel=tabel, familiya=fam, ism=ism, otasi=ota,
                    position=pos_map.get(pos_idx),
                    ish_joyi=depo.nomi,
                    kirgan_sana=today(),
                    jinsi="ayol" if ism.endswith("a") else "erkak",
                    roles=roles, faol=True,
                )
                w.set_unusable_password()
                w.save(update_fields=["password"])
                if w.position:
                    w.positions.set([w.position])

                Card.objects.get_or_create(worker=w, defaults={"ochilgan": today()})
                for r in (1, 2, 3):
                    Talon.objects.get_or_create(worker=w, raqam=r, defaults={"olingan": False})
                Exam.objects.get_or_create(
                    worker=w,
                    defaults={"oxirgi": add_months(today(), -11),
                              "davriylik_oy": 12, "natija": "otdi"},
                )
                qoshildi += 1
            self.stdout.write(f"  Namunaviy xodimlar: +{qoshildi}")

        # --- administrator ---
        tabel = (o["admin"] or "").strip()
        if tabel:
            # F.I.Sh. berilgan boʻlsa boʻlaklarga ajratamiz
            bolak = (o["fio"] or "").split()
            familiya = bolak[0] if bolak else "Administrator"
            ism = bolak[1] if len(bolak) > 1 else tabel
            otasi = " ".join(bolak[2:]) if len(bolak) > 2 else ""

            w, yangi = Worker.objects.get_or_create(
                tabel=tabel,
                defaults={
                    "depo": depo,
                    "familiya": familiya, "ism": ism, "otasi": otasi,
                    "roles": ["admin"], "faol": True, "is_staff": True,
                    "is_superuser": True, "ish_joyi": depo.nomi,
                    "kirgan_sana": today(),
                    "position": pos_map.get(28),   # Mehnat muhofazasi muhandisi
                },
            )
            if not yangi:
                w.roles = sorted(set((w.roles or []) + ["admin"]))
                w.is_staff = w.is_superuser = True
                w.faol = True
                if o["fio"]:
                    w.familiya, w.ism, w.otasi = familiya, ism, otasi

            if o["pin"]:
                w.set_pin(o["pin"])
            else:
                # PIN berilmadi — ishchi birinchi kirishda oʻzi oʻrnatadi
                w.pin_hash = ""
                w.pin_reset = False

            w.set_unusable_password()
            w.save()

            if w.position:
                w.positions.set([w.position])

            Card.objects.get_or_create(worker=w, defaults={"ochilgan": today()})
            for r in (1, 2, 3):
                Talon.objects.get_or_create(worker=w, raqam=r, defaults={"olingan": False})

            holat = "yaratildi" if yangi else "yangilandi"
            self.stdout.write(f"  Administrator {tabel} ({w.fio}) — {holat}")
            if o["pin"]:
                self.stdout.write(self.style.WARNING(
                    "  PIN oʻrnatildi — birinchi kirishdan keyin almashtiring"))
            else:
                self.stdout.write(
                    "  PIN oʻrnatilmagan — birinchi kirishda oʻzingiz tanlaysiz")

        self.stdout.write(self.style.SUCCESS("Tayyor."))
