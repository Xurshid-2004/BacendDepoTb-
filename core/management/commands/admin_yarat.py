"""
=====================================================================
Administrator hisobini tayyorlaydi (serverga birinchi kirish uchun).

    python manage.py admin_yarat --tabel 0212
    python manage.py admin_yarat --tabel 0212 --pin 1234
    python manage.py admin_yarat                  # muhit oʻzgaruvchilaridan

Muhit oʻzgaruvchilari (Railway/Render panelida yoziladi):
    TB_ADMIN_TABEL=0212
    TB_ADMIN_PIN=1234        # ixtiyoriy
    TB_ADMIN_FIO="Abduvaliyev Ohun Olimjon oʻgʻli"   # ixtiyoriy

Nega alohida buyruq (`seed --admin` bor-ku):
`seed --admin ... --pin ...` PIN'ni HAR SAFAR qayta oʻrnatadi. Uni
deploy zanjiriga qoʻysak, administrator PIN'ini oʻzgartirsa ham
keyingi deploy uni eski qiymatga qaytarib qoʻyardi.

Bu buyruq esa **bir marta** ishlaydi:
  • hisob yoʻq boʻlsa      — yaratadi;
  • hisob bor boʻlsa       — faqat admin roli va faolligini kafolatlaydi,
                             PIN'ga TEGMAYDI.

PIN berilmasa hisob PIN'siz yaratiladi — administrator birinchi kirishda
tabel raqamini terib, oʻziga PIN yaratadi (eng xavfsiz yoʻl: parol
muhit oʻzgaruvchisida umuman saqlanmaydi).
=====================================================================
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand
from django.db import transaction

from core.logic import today
from core.models import Card, Depo, Talon, Worker


class Command(BaseCommand):
    help = "Administrator hisobini yaratadi (mavjud boʻlsa — tegmaydi)"

    def add_arguments(self, parser):
        parser.add_argument("--tabel", type=str, default="", help="Tabel raqami")
        parser.add_argument("--pin", type=str, default="", help="Boshlangʻich PIN (ixtiyoriy)")
        parser.add_argument("--fio", type=str, default="", help="F.I.Sh. (ixtiyoriy)")

    @transaction.atomic
    def handle(self, *args, **o):
        tabel = (o["tabel"] or os.environ.get("TB_ADMIN_TABEL", "")).strip()
        pin = (o["pin"] or os.environ.get("TB_ADMIN_PIN", "")).strip()
        fio = (o["fio"] or os.environ.get("TB_ADMIN_FIO", "")).strip()

        if not tabel:
            self.stdout.write("TB_ADMIN_TABEL berilmagan — oʻtkazib yuborildi")
            return

        w = Worker.objects.filter(tabel=tabel).first()

        if w:
            # Mavjud hisob — PIN'ga tegilmaydi, faqat huquq kafolatlanadi
            oldingi = list(w.roles or [])
            w.roles = sorted(set(oldingi + ["admin"]))
            w.is_staff = w.is_superuser = True
            w.faol = True
            w.deleted = False
            w.save(update_fields=["roles", "is_staff", "is_superuser", "faol", "deleted"])
            oz = "roli yangilandi" if w.roles != sorted(set(oldingi)) else "oʻzgarishsiz"
            self.stdout.write(self.style.SUCCESS(
                f"Administrator {tabel} allaqachon bor — {oz} (PIN'ga tegilmadi)"
            ))
            return

        bolak = fio.split()
        w = Worker.objects.create(
            depo=Depo.joriy(),
            tabel=tabel,
            familiya=bolak[0] if bolak else "Administrator",
            ism=bolak[1] if len(bolak) > 1 else tabel,
            otasi=" ".join(bolak[2:]) if len(bolak) > 2 else "",
            roles=["admin"],
            faol=True,
            is_staff=True,
            is_superuser=True,
            ish_joyi=Depo.joriy().nomi,
            kirgan_sana=today(),
        )
        w.set_unusable_password()
        if pin:
            w.set_pin(pin)
        w.save()

        Card.objects.get_or_create(worker=w, defaults={"ochilgan": today()})
        for n in (1, 2, 3):
            Talon.objects.get_or_create(worker=w, raqam=n, defaults={"olingan": False})

        if pin:
            self.stdout.write(self.style.SUCCESS(
                f"Administrator {tabel} yaratildi (PIN oʻrnatildi). "
                "Birinchi kirishdan keyin PIN'ni almashtiring va "
                "TB_ADMIN_PIN oʻzgaruvchisini oʻchiring."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Administrator {tabel} yaratildi — PIN'siz. "
                "Kirish sahifasida shu tabel raqamini tersangiz, "
                "oʻzingizga PIN yaratasiz."
            ))
