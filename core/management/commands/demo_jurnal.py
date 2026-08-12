"""
=====================================================================
TB jurnaliga namunaviy yozuvlar (koʻrsatish uchun).

    python manage.py demo_jurnal              # 1-bosqichga 4 ta yozuv
    python manage.py demo_jurnal --bosqich 2  # 2-bosqichga
    python manage.py demo_jurnal --tozala     # namunalarni oʻchiradi

Yozuvlar HAQIQIY xodimlar nomidan tuziladi (kadrlar bazasidan olinadi):
  • komissiya — ish beruvchi (TB muhandisi + katta usta)
  • javobgar  — ish oluvchi (chora-tadbirni bajaradigan xodim)

Ikkitasi tasdiqlangan (QR imzo bilan), ikkitasi muddati oʻtgan — jadval
qanday koʻrinishini toʻliq koʻrsatadi.

DIQQAT: bu NAMUNA maʼlumot. Haqiqiy jurnal yuritishdan oldin
`--tozala` bilan oʻchirib tashlang.
=====================================================================
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import logic
from core.models import JournalEntry, Signature, Worker

IZOH = "NAMUNA"          # namunaviy yozuvlarni ajratish uchun belgi

# (kun_oldin, nomuvofiqlik, chora, muddat_kun, bajarildimi)
NAMUNALAR = [
    (
        4,
        "Akkumulyator boʻlimida soʻrgʻich ventilyatsiya kuchsiz",
        "Ventilyatorni almashtirish va kanalni tozalash",
        7,
        True,
    ),
    (
        7,
        "PTO sexida himoya kaskalari yetishmayapti (4 dona)",
        "Omborxonaga talabnoma yuborish",
        4,
        False,
    ),
    (
        10,
        "Payvandlash postida ekran oʻrnatilmagan",
        "Koʻchma himoya ekranini oʻrnatish",
        1,
        False,
    ),
    (
        13,
        "Yongʻin oʻchirgichlar muddati oʻtgan (3 dona)",
        "Zaryadlash va qayta sertifikatlash",
        -2,
        True,
    ),
]


class Command(BaseCommand):
    help = "TB jurnaliga namunaviy yozuvlar qoʻshadi (demo)"

    def add_arguments(self, parser):
        parser.add_argument("--bosqich", type=int, default=1, choices=[1, 2])
        parser.add_argument("--tozala", action="store_true", help="Namunalarni oʻchirish")

    @transaction.atomic
    def handle(self, *args, **o):
        if o["tozala"]:
            n = JournalEntry.objects.filter(bajarilgan_izoh__startswith=IZOH).count()
            JournalEntry.objects.filter(bajarilgan_izoh__startswith=IZOH).delete()
            self.stdout.write(self.style.SUCCESS(f"{n} ta namunaviy yozuv oʻchirildi"))
            return

        bosqich = o["bosqich"]

        # --- komissiya (ish beruvchi) ---
        # roles — JSONField; `contains` lookup SQLite'da ishlamaydi,
        # shuning uchun lavozim nomi boʻyicha qidiramiz.
        tb = (
            Worker.objects.filter(
                position__nomi__icontains="texnika xavfsizligi", deleted=False
            ).first()
            or next(
                (w for w in Worker.objects.filter(deleted=False) if "tb_xodim" in (w.roles or [])),
                None,
            )
        )
        usta = (
            Worker.objects.filter(position__nomi__icontains="Katta usta", deleted=False).first()
            or Worker.objects.filter(position__nomi__icontains="Usta", deleted=False).first()
        )
        if not tb:
            self.stderr.write("Kadrlar bazasi boʻsh — avval `import_xodimlar` ni bajaring")
            return

        komissiya = [{
            "fio": tb.fio,
            "lavozim": tb.position.nomi if tb.position else "TB muhandisi",
        }]
        if usta and usta.id != tb.id:
            komissiya.append({
                "fio": usta.fio,
                "lavozim": usta.position.nomi if usta.position else "Katta usta",
            })

        # --- javobgarlar (ish oluvchi) — turli xodimlar ---
        javobgarlar = list(
            Worker.objects.filter(deleted=False, faol=True)
            .exclude(id__in=[w.id for w in (tb, usta) if w])
            .order_by("tabel")[:len(NAMUNALAR)]
        )
        if len(javobgarlar) < len(NAMUNALAR):
            self.stderr.write("Xodimlar yetarli emas")
            return

        bugun = logic.today()
        qoshildi = 0
        for (kun, nomuvofiqlik, chora, muddat_kun, bajarildi), j in zip(NAMUNALAR, javobgarlar):
            if JournalEntry.objects.filter(bosqich=bosqich, nomuvofiqlik=nomuvofiqlik).exists():
                continue

            e = JournalEntry.objects.create(
                bosqich=bosqich,
                sana=bugun - timedelta(days=kun),
                komissiya=komissiya,
                nomuvofiqlik=nomuvofiqlik,
                chora=chora,
                masul=j.fio,
                masul_lavozim=j.position.nomi if j.position else "Ishchi",
                muddat=bugun + timedelta(days=muddat_kun),
                bajarildi=bajarildi,
                bajarilgan_izoh=f"{IZOH} · bajarildi, tekshirildi" if bajarildi else IZOH,
            )

            # Tasdiqlangan yozuvga QR imzo — TB muhandisi nomidan
            if bajarildi:
                e.imzo = Signature.objects.create(
                    doc_type="journal",
                    doc_id=str(e.id),
                    field="07",
                    user=tb,
                    sana=timezone.now() - timedelta(days=max(kun - 2, 0)),
                    hash=logic.make_hash(f"journal{e.id}07{tb.id}"),
                    payload={
                        "fio": tb.fio,
                        "lavozim": tb.position.nomi if tb.position else "TB muhandisi",
                        "sana": (bugun - timedelta(days=max(kun - 2, 0))).isoformat(),
                    },
                )
                e.save(update_fields=["imzo"])
            qoshildi += 1

        self.stdout.write(self.style.SUCCESS(
            f"{bosqich}-bosqich jurnaliga {qoshildi} ta namunaviy yozuv qoʻshildi"
        ))
        self.stdout.write(f"Komissiya (ish beruvchi): {', '.join(k['fio'] for k in komissiya)}")
        self.stdout.write("Oʻchirish: python manage.py demo_jurnal --tozala")
