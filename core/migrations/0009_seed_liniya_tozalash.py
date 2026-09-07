"""Seed'dagi 6 ta namunaviy liniyani roʻyxatdan olib tashlash.

Yoʻriqchilar liniyani oʻzi kiritadi. Bu faqat TAKLIF roʻyxatidan
oʻchiradi — KIP yozuvlarining liniya matni (Kip.liniya) erkin matn
boʻlgani uchun tegilmaydi va yoʻqolmaydi. Agar oʻsha nom keyin qayta
yozilsa, views_ops._liniya_saqla uni roʻyxatga qayta qoʻshadi.
"""

from django.db import migrations

SEED_LINES = [
    "Buxoro — Qorakoʻl",
    "Buxoro — Navoiy",
    "Buxoro-1 stansiyasi",
    "Qiziltepa — Buxoro",
    "Kogon stansiyasi",
    "Buxoro — Olot",
]


def olib_tashla(apps, schema_editor):
    Line = apps.get_model("core", "Line")
    Line.objects.filter(nomi__in=SEED_LINES).delete()


def qayta_qosh(apps, schema_editor):
    # Orqaga qaytarilsa — seed liniyalari tiklanadi.
    Line = apps.get_model("core", "Line")
    for i, nomi in enumerate(SEED_LINES):
        Line.objects.get_or_create(nomi=nomi, defaults={"tartib": i + 1})


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_kip_muddat_kun"),
    ]

    operations = [
        migrations.RunPython(olib_tashla, qayta_qosh),
    ]
