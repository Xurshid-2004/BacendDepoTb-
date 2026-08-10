"""
=====================================================================
Biznes-mantiq — frontend'dagi lib/logic.ts ning server koʻchirmasi.

Endi bu qoidalar SERVERDA qaror qiladi: ariza yuborish mumkinmi,
keyingi holat qaysi, muddat oʻtganmi. Frontend xuddi shu hisobni
koʻrsatish uchun bajaradi, lekin yakuniy soʻz shu yerda.
=====================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

# ---------------------------------------------------------------------
# Sana yordamchilari
# ---------------------------------------------------------------------

def today() -> date:
    return timezone.localdate()


def add_months(d: date, m: int) -> date:
    """Sanaga oy qoʻshish — oy oxiri chegarasini hisobga oladi."""
    yil = d.year + (d.month - 1 + m) // 12
    oy = (d.month - 1 + m) % 12 + 1
    # Oyning oxirgi kunidan oshib ketmasligi uchun
    keyingi_oy_boshi = date(yil + (oy // 12), (oy % 12) + 1, 1)
    oxirgi_kun = (keyingi_oy_boshi - timedelta(days=1)).day
    return date(yil, oy, min(d.day, oxirgi_kun))


def days_between(a: date, b: date) -> int:
    return (b - a).days


# ---------------------------------------------------------------------
# Qishki mavsum
# ---------------------------------------------------------------------

def season_open(depo, at: date | None = None) -> bool:
    """
    Qishki buyumlar mavsumi ochiqmi (masalan 15-sentabr → 15-aprel).
    Mavsum yil chegarasidan oʻtadi, shuning uchun "yoki" mantigʻi.
    """
    at = at or today()
    try:
        sm, sd = (int(x) for x in depo.qish_boshi.split("-"))
        em, ed = (int(x) for x in depo.qish_oxiri.split("-"))
    except (ValueError, AttributeError):
        return True

    start = date(at.year, sm, sd)
    end = date(at.year, em, ed)
    return at >= start or at <= end


# ---------------------------------------------------------------------
# Normalar
# ---------------------------------------------------------------------

def norms_for_worker(worker) -> list:
    """
    Ishchining barcha lavozimlari boʻyicha normalar.
    Bitta buyum bir nechta lavozimda boʻlsa — eng qisqa muddatlisi olinadi.
    """
    from core.models import Norm

    pids = worker.position_ids()
    if not pids:
        return []

    by_item: dict[str, object] = {}
    qs = Norm.objects.filter(position_id__in=pids).select_related("item", "position")
    for n in qs:
        key = str(n.item_id)
        cur = by_item.get(key)
        if cur is None:
            by_item[key] = n
            continue
        cur_m = float("inf") if cur.muddat_oy is None else cur.muddat_oy
        new_m = float("inf") if n.muddat_oy is None else n.muddat_oy
        if new_m < cur_m:
            by_item[key] = n
    return list(by_item.values())


def last_issue(card, item_id) -> date | None:
    """Buyumning oxirgi berilgan sanasi."""
    if not card:
        return None
    row = (
        card.berilgan.filter(item_id=item_id)
        .order_by("-sana")
        .values_list("sana", flat=True)
        .first()
    )
    return row


@dataclass
class ItemState:
    item_id: str
    norm: object
    oxirgi: date | None = None
    keyingi: date | None = None
    qolgan_kun: int | None = None
    holat: str = "sariq"        # yashil | sariq | qizil | chiqqun


def item_states(worker, at: date | None = None) -> list[ItemState]:
    """Ishchining har bir norma buyumi boʻyicha holati."""
    from core.models import Card

    at = at or today()
    card = Card.objects.filter(worker=worker).first()

    out: list[ItemState] = []
    for norm in norms_for_worker(worker):
        oxirgi = last_issue(card, norm.item_id)

        if norm.muddat_oy is None:
            out.append(ItemState(str(norm.item_id), norm, oxirgi, holat="chiqqun"))
            continue

        if not oxirgi:
            out.append(ItemState(str(norm.item_id), norm, holat="sariq", qolgan_kun=0))
            continue

        keyingi = add_months(oxirgi, norm.muddat_oy)
        qolgan = days_between(at, keyingi)
        if qolgan > 30:
            holat = "yashil"
        elif qolgan >= -30:
            holat = "sariq"
        else:
            holat = "qizil"
        out.append(ItemState(str(norm.item_id), norm, oxirgi, keyingi, qolgan, holat))
    return out


def can_request(worker, item_id, at: date | None = None) -> tuple[bool, str]:
    """
    Ishchi shu buyumga ariza yubora oladimi.
    Qaytaradi: (mumkinmi, sabab)
    """
    from core.models import Item, Request

    at = at or today()

    st = next((s for s in item_states(worker, at) if s.item_id == str(item_id)), None)
    if not st:
        return False, "Bu buyum sizning lavozimingiz normasida yoʻq"

    item = Item.objects.filter(id=item_id).first()
    if not item:
        return False, "Buyum topilmadi"

    if item.qishki and not season_open(worker.depo, at):
        return False, "Qishki buyumlar arizasi 15-sentabrdan 15-aprelgacha qabul qilinadi"

    ochiq = (
        Request.objects.filter(worker=worker, lines__item_id=item_id)
        .exclude(status__in=["COMPLETED", "REJECTED"])
        .exists()
    )
    if ochiq:
        return False, "Bu buyum boʻyicha yakunlanmagan arizangiz bor"

    if st.holat == "chiqqun":
        return True, ""
    if st.holat == "yashil":
        sana = st.keyingi.strftime("%d.%m.%Y") if st.keyingi else ""
        return False, f"Olish muddati hali kelmagan. Keyingi sana: {sana}"
    return True, ""


# ---------------------------------------------------------------------
# Ariza holatlari (state machine)
# ---------------------------------------------------------------------

NEXT_STATUS: dict[str, str] = {
    "SUBMITTED": "ACCOUNTANT_APPROVED",
    "ACCOUNTANT_APPROVED": "CHIEF_APPROVED",
    "CHIEF_APPROVED": "HEAD_APPROVED",
    "HEAD_APPROVED": "ISSUED",
    "ISSUED": "RECEIVED",
    "RECEIVED": "COMPLETED",
}

# Har bosqichda qaysi rol harakat qila oladi
ACTOR_ROLE: dict[str, str | None] = {
    "SUBMITTED": "bugalter",
    "ACCOUNTANT_APPROVED": "bosh_xisobchi",
    "CHIEF_APPROVED": "depo_boshligi",
    "HEAD_APPROVED": "ombor_mudiri",
    "ISSUED": None,        # ishchining oʻzi tasdiqlaydi
    "RECEIVED": "ombor_mudiri",
}

# Har bosqichda Требование blankasining qaysi maydoni imzolanadi
SIGN_FIELD: dict[str, str] = {
    "SUBMITTED": "06",
    "ACCOUNTANT_APPROVED": "14",
    "CHIEF_APPROVED": "05",
    "HEAD_APPROVED": "11",
    "ISSUED": "12",
}

STATUS_ORDER: list[str] = [
    "SUBMITTED", "ACCOUNTANT_APPROVED", "CHIEF_APPROVED",
    "HEAD_APPROVED", "ISSUED", "RECEIVED", "COMPLETED",
]


def next_status(s: str) -> str | None:
    return NEXT_STATUS.get(s)


def stage_index(s: str) -> int:
    return STATUS_ORDER.index(s) if s in STATUS_ORDER else -1


def can_advance(worker, request_obj) -> tuple[bool, str]:
    """
    Ishchi shu arizani keyingi bosqichga oʻtkaza oladimi.
    Serverda majburiy tekshiruv — frontend tugmani yashirgan boʻlsa ham.
    """
    if worker.has_role("admin"):
        return (True, "") if next_status(request_obj.status) else (False, "Ariza allaqachon yakunlangan")

    to = next_status(request_obj.status)
    if not to:
        return False, "Ariza allaqachon yakunlangan yoki rad etilgan"

    # ISSUED → RECEIVED: faqat arizaning egasi tasdiqlaydi
    if request_obj.status == "ISSUED":
        if str(request_obj.worker_id) != str(worker.id):
            return False, "Buyumni olganini faqat ishchining oʻzi tasdiqlaydi"
        return True, ""

    kerak = ACTOR_ROLE.get(request_obj.status)
    if kerak and not worker.has_role(kerak):
        return False, "Bu bosqichda harakat qilish huquqingiz yoʻq"
    return True, ""


def reject_reason_required(roles: list[str]) -> bool:
    """Rad etish sababi majburiymi — depo boshligʻidan tashqari hamma uchun ha."""
    return "depo_boshligi" not in (roles or [])


# ---------------------------------------------------------------------
# KIP ranglari
# ---------------------------------------------------------------------

def kip_tone(tugash: date, at: date | None = None) -> dict:
    at = at or today()
    d = days_between(at, tugash)
    if d < 0:
        return {"label": "Muddati oʻtdi", "color": "#b91c1c", "qism": 4}
    if d == 0:
        return {"label": "Bugun tugaydi", "color": "#f97316", "qism": 3}
    if d <= 2:
        return {"label": f"{d} kun qoldi", "color": "#f59e0b", "qism": 2}
    if d <= 3:
        return {"label": f"{d} kun qoldi", "color": "#22c55e", "qism": 1}
    return {"label": f"{d} kun qoldi", "color": "#38bdf8", "qism": 0}


# ---------------------------------------------------------------------
# Imzo hash — lib/logic.ts makeHash bilan bir xil (FNV asosidagi)
# ---------------------------------------------------------------------

def make_hash(text: str) -> str:
    """
    Frontend'dagi makeHash bilan bir xil natija beradi.
    32-bitli arifmetika JS'dagidek maskalanadi.
    """
    M = 0xFFFFFFFF
    h1 = 0x811C9DC5
    h2 = 0x01000193
    for i, ch in enumerate(text):
        c = ord(ch)
        h1 = (h1 ^ c) & M
        h1 = (h1 * 0x01000193) & M
        h2 = (((h2 ^ c) * 0x85EBCA6B) + i) & M
    return f"{h1:08x}{h2:08x}".upper()


# ---------------------------------------------------------------------
# Ariza raqami
# ---------------------------------------------------------------------

def next_req_no(depo) -> str:
    """
    Keyingi ariza raqami — TCH6-YYYY-NNNNN.
    Depo.seq atomik oshiriladi (F ifodasi bilan) — 800 foydalanuvchi
    bir vaqtda ariza yuborsa ham raqam takrorlanmaydi.
    """
    from django.db.models import F

    from core.models import Depo

    Depo.objects.filter(pk=depo.pk).update(seq=F("seq") + 1)
    seq = Depo.objects.filter(pk=depo.pk).values_list("seq", flat=True).first() or 1

    prefiks = depo.kod.replace("-", "").upper()
    return f"{prefiks}-{today().year}-{seq:05d}"


# ---------------------------------------------------------------------
# Dashboard statistikasi
# ---------------------------------------------------------------------

def dashboard_stats() -> dict:
    from core.models import JournalEntry, Kip, Request, Worker

    bugun = today()

    ochiq_jurnal = JournalEntry.objects.filter(bajarildi=False)
    muddat_yaqin = ochiq_jurnal.filter(
        muddat__gte=bugun, muddat__lte=bugun + timedelta(days=3)
    ).count()
    muddat_otgan = ochiq_jurnal.filter(muddat__lt=bugun).count()

    faol_ariza = Request.objects.exclude(status__in=["COMPLETED", "REJECTED"]).count()

    kelgan = otgan = 0
    for w in Worker.objects.filter(faol=True, deleted=False).prefetch_related("positions"):
        st = item_states(w, bugun)
        if any(s.holat == "sariq" for s in st):
            kelgan += 1
        if any(s.holat == "qizil" for s in st):
            otgan += 1

    kip_otgan = kip_yaqin = 0
    for k in Kip.objects.all():
        qism = kip_tone(k.tugash, bugun)["qism"]
        if qism == 4:
            kip_otgan += 1
        elif qism in (1, 2, 3):
            kip_yaqin += 1

    return {
        "ochiqJurnal": ochiq_jurnal.count(),
        "muddatYaqin": muddat_yaqin,
        "muddatOtgan": muddat_otgan,
        "faolAriza": faol_ariza,
        "kelgan": kelgan,
        "otgan": otgan,
        "kipOtgan": kip_otgan,
        "kipYaqin": kip_yaqin,
    }
