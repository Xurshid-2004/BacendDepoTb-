# Koʻrik boʻlimlari (tibbiy koʻrik + psixolog) uchun yangi jadval.
# Mavjud maʼlumotga tegmaydi — faqat Korik jadvali qoʻshiladi va
# Signature.doc_type roʻyxatiga "korik" qiymati kiritiladi.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_seed_liniya_tozalash"),
    ]

    operations = [
        migrations.CreateModel(
            name="Korik",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "turi",
                    models.CharField(
                        choices=[("tibbiy", "Tibbiy koʻrik"), ("psixolog", "Psixolog")],
                        max_length=16,
                    ),
                ),
                ("sana", models.DateField(blank=True, null=True)),
                (
                    "muddat_oy",
                    models.IntegerField(
                        blank=True,
                        help_text="Psixolog: 3/6/12; tibbiy: boʻsh",
                        null=True,
                    ),
                ),
                ("tugash", models.DateField()),
                ("imzo_id", models.CharField(blank=True, max_length=64)),
                ("izoh", models.CharField(blank=True, max_length=255)),
                (
                    "belgilagan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bergan_koriklar",
                        to="core.worker",
                    ),
                ),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="koriklar",
                        to="core.worker",
                    ),
                ),
            ],
            options={
                "verbose_name": "Koʻrik",
                "verbose_name_plural": "Koʻriklar",
                "ordering": ["tugash"],
            },
        ),
        migrations.AddIndex(
            model_name="korik",
            index=models.Index(fields=["turi", "tugash"], name="korik_turi_tugash_idx"),
        ),
        migrations.AddConstraint(
            model_name="korik",
            constraint=models.UniqueConstraint(
                fields=["worker", "turi"], name="korik_worker_turi_uniq"
            ),
        ),
        migrations.AlterField(
            model_name="signature",
            name="doc_type",
            field=models.CharField(
                choices=[
                    ("journal", "Jurnal"),
                    ("requisition", "Требование"),
                    ("card", "Kartochka"),
                    ("kip", "KIP"),
                    ("card_id", "ID karta"),
                    ("tnu19", "TNU-19 (depo navbatchisi)"),
                    ("yo_d26b", "Yo D-26 (instruktor yoʻriqnoma)"),
                    ("korik", "Koʻrik (tibbiy/psixolog)"),
                ],
                max_length=32,
            ),
        ),
    ]
