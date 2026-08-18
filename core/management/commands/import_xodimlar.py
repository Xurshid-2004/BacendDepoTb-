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


def kolonna_top(r: dict) -> str:
    """Xodim qaysi kolonnada ishlaydi — «17-Manyovr kolonnasi», «18 -Elektrovoz
    xizmati kolonnasi» kabi. Kadrlar jadvalida u lavozim satrining slashlar
    orasidagi qismi (JSON'da «sex» maydoni) boʻlib keladi. KIP roʻyxati va
    ishchi kartochkasi shu ustunni koʻrsatadi."""
    qiymat = str(r.get("kolonna") or r.get("sex") or "").strip(" -")
    return qiymat[:64]


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

        # Mavjud xodimlar bitta soʻrovda olinadi (tabel boʻyicha)
        tabellar = [str(r["tabel"]).strip() for r in rows if str(r.get("tabel", "")).strip()]
        mavjud = {
            w.tabel: w
            for w in Worker.objects.filter(tabel__in=tabellar).prefetch_related("positions")
        }

        yangilar: list[Worker] = []            # bulk_create uchun
        yangilanadi: list[Worker] = []         # bulk_update uchun
        yangi_lavozim: list[tuple] = []        # (worker, position)
        lavozim_ozgardi: list[tuple] = []      # mavjud xodimning lavozimi oʻzgargan

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
            w = mavjud.get(tabel)

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
                w.kolonna = kolonna_top(r)
                w.ish_joyi = r["lavozimToliq"]
                w.jinsi = r["jinsi"]
                if position:
                    w.position = position
                if rasm:
                    w.rasm = rasm
                if not w.roles:
                    w.roles = [rol_top(r["lavozim"])]
                yangilanadi.append(w)
                if position and [position.id] != [p.id for p in w.positions.all()]:
                    lavozim_ozgardi.append((w, position))
                yangilandi += 1
                continue

            w = Worker(
                depo=depo,
                tabel=tabel,
                familiya=r["familiya"],
                ism=r["ism"],
                otasi=r["otasi"],
                position=position,
                sex=r["sex"],
                kolonna=kolonna_top(r),
                ish_joyi=r["lavozimToliq"],
                kirgan_sana=today(),
                jinsi=r["jinsi"],
                roles=[rol_top(r["lavozim"])],
                faol=True,
                rasm=rasm,
            )
            w.set_unusable_password()          # kirish faqat PIN orqali
            yangilar.append(w)
            if position:
                yangi_lavozim.append((w, position))
            qoshildi += 1

        if o["quruq"]:
            self.stdout.write(self.style.WARNING("Quruq rejim — bazaga hech narsa yozilmadi"))
            return

        # --- bazaga yozish: bittalab emas, toʻda-toʻda ------------------
        # 296 xodimni bittalab yozish uzoq bazaga ~1800 ta soʻrov edi va
        # bir necha daqiqa olardi. Bu yerda soʻrovlar soni oʻnga tushadi.
        if yangilar:
            Worker.objects.bulk_create(yangilar, batch_size=100)
        if yangilanadi:
            Worker.objects.bulk_update(
                yangilanadi,
                ["familiya", "ism", "otasi", "sex", "kolonna", "ish_joyi", "jinsi",
                 "position", "rasm", "roles"],
                batch_size=100,
            )

        # Lavozim bogʻlanishi (many-to-many)
        Aloqa = Worker.positions.through
        if yangi_lavozim:
            Aloqa.objects.bulk_create(
                [Aloqa(worker_id=w.id, position_id=p.id) for w, p in yangi_lavozim],
                batch_size=200, ignore_conflicts=True,
            )
        for w, p in lavozim_ozgardi:          # kam uchraydi — faqat oʻzgarganlar
            w.positions.set([p])

        # Kartochka va talonlar — faqat yangi xodimlar uchun
        if yangilar:
            Card.objects.bulk_create(
                [Card(worker=w, ochilgan=today()) for w in yangilar],
                batch_size=200, ignore_conflicts=True,
            )
            Talon.objects.bulk_create(
                [Talon(worker=w, raqam=n, olingan=False) for w in yangilar for n in (1, 2, 3)],
                batch_size=300, ignore_conflicts=True,
            )

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
