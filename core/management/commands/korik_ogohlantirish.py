"""
Koʻrik ogohlantirishi — kuniga bir marta ishga tushiriladi.

Muddati (qayta oʻtish sanasi) 1 oy ichida tugaydigan tibbiy koʻrik va
psixolog yozuvlari boʻyicha ISHCHINING oʻziga bildirishnoma yuboradi.

Bir yozuv uchun bir marta yuboriladi (dedupe): bildirishnoma matnida
`[turi:sana]` belgisi boʻladi; sana oʻzgarsa (yangi koʻrik kiritilsa)
yangi belgi hosil boʻlib, yangi ogohlantirish yuboriladi.

Ishga tushirish (kuniga bir marta, cron/scheduler orqali):
    python manage.py korik_ogohlantirish
    python manage.py korik_ogohlantirish --kun 30
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Korik, Notification

NOM = {"tibbiy": "Tibbiy koʻrik", "psixolog": "Psixolog"}


class Command(BaseCommand):
    help = "Muddati 1 oy ichida tugaydigan koʻriklar boʻyicha ishchini ogohlantiradi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--kun", type=int, default=30,
            help="Necha kun oldin ogohlantirish (standart 30)",
        )

    def handle(self, *args, **opts):
        bugun = timezone.localdate()
        chegara = bugun + timedelta(days=opts["kun"])

        yuborildi = 0
        qs = (
            Korik.objects.filter(tugash__gte=bugun, tugash__lte=chegara)
            .select_related("worker")
        )
        for k in qs:
            nom = NOM.get(k.turi, "Koʻrik")
            belgi = f"[{k.turi}:{k.tugash.isoformat()}]"
            takror = Notification.objects.filter(
                worker_id=k.worker_id, turi="korik_ogoh", matn__contains=belgi
            ).exists()
            if takror:
                continue
            qolgan = (k.tugash - bugun).days
            Notification.objects.create(
                worker_id=k.worker_id,
                turi="korik_ogoh",
                sarlavha=f"{nom} muddati yaqinlashdi",
                matn=(
                    f"{nom} qayta oʻtish sanasi: {k.tugash.isoformat()} "
                    f"({qolgan} kun qoldi). Iltimos, oʻz vaqtida oʻting. {belgi}"
                ),
            )
            yuborildi += 1

        self.stdout.write(self.style.SUCCESS(f"Koʻrik ogohlantirishi yuborildi: {yuborildi}"))
