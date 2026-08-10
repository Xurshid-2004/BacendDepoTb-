"""
=====================================================================
Ruxsatlar va koʻrinish tizimi.

Bu modul frontend'dagi lib/permissions.ts ning aynan koʻchirmasi.
MUHIM: ikkala fayl bir xil qoidani ifodalaydi — birini oʻzgartirsangiz,
ikkinchisini ham oʻzgartiring. Yakuniy qaror HAR DOIM shu yerda
(serverda) qabul qilinadi; frontend faqat tugmani koʻrsatish/yashirish
uchun ishlatadi.

Ustuvorlik: shaxs → lavozim → rol override → rol standarti.
=====================================================================
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

# ---------------------------------------------------------------------
# Ruxsatlar (resurs.amal)
# ---------------------------------------------------------------------

ALL_PERMS: list[str] = [
    "journal.read", "journal.write", "journal.sign",
    "request.create", "request.approve1", "request.approve2", "request.approve3",
    "request.issue", "request.receive",
    "stock.read", "stock.write",
    "card.read", "card.create",
    "talon.read", "talon.write", "exam.write",
    "kip.read", "kip.write",
    "report.read", "report.download",
    "admin.users", "admin.norms", "admin.settings",
    "incident.tb.write", "incident.tb.read",
    "incident.avariya.write", "incident.avariya.read",
]

PERM_LABEL: dict[str, str] = {
    "journal.read": "Jurnalni koʻrish",
    "journal.write": "Jurnalga yozuv qoʻshish",
    "journal.sign": "Jurnal 7-ustunini imzolash",
    "request.create": "Ariza yuborish",
    "request.approve1": "Ariza tasdiqlash — 1-bosqich",
    "request.approve2": "Ariza tasdiqlash — 2-bosqich",
    "request.approve3": "Ariza tasdiqlash — 3-bosqich",
    "request.issue": "Ombordan berish",
    "request.receive": "Olganlikni tasdiqlash",
    "stock.read": "Ombor qoldigʻini koʻrish",
    "stock.write": "Buyum kirim qilish",
    "card.read": "Kartochkani koʻrish",
    "card.create": "Kartochka ochish",
    "talon.read": "Talonlarni koʻrish",
    "talon.write": "Talon olish / qaytarish",
    "exam.write": "Imtixon sanasini belgilash",
    "kip.read": "KIP koʻrish",
    "kip.write": "KIP yozish",
    "report.read": "Hisobotlarni koʻrish",
    "report.download": "Hisobotlarni yuklab olish",
    "admin.users": "Foydalanuvchilarni boshqarish",
    "admin.norms": "Normalarni tahrirlash",
    "admin.settings": "Tizim sozlamalari",
    "incident.tb.write": "TB: baxtsiz xodisa yozish",
    "incident.tb.read": "TB: baxtsiz xodisalarni koʻrish",
    "incident.avariya.write": "Yoʻriqchi: avariya yozish",
    "incident.avariya.read": "Yoʻriqchi: avariyalarni koʻrish",
}

ROLE_PERMS: dict[str, list[str]] = {
    "admin": list(ALL_PERMS),
    "depo_boshligi": [
        "journal.read", "journal.write", "journal.sign",
        "request.approve3", "stock.read", "card.read",
        "talon.read", "kip.read", "report.read", "report.download",
        "incident.tb.read", "incident.avariya.read",
    ],
    "bosh_xisobchi": [
        "journal.read", "request.approve2", "stock.read", "card.read",
        "talon.read", "report.read", "report.download",
        "incident.tb.read", "incident.avariya.read",
    ],
    "bugalter": [
        "journal.read", "request.approve1", "stock.read", "card.read",
        "talon.read", "report.read", "report.download",
        "incident.tb.read", "incident.avariya.read",
    ],
    "tb_xodim": [
        "journal.read", "journal.write", "journal.sign",
        "request.create", "card.read", "card.create",
        "talon.read", "talon.write", "exam.write",
        "kip.read", "report.read", "report.download",
        "incident.tb.write", "incident.tb.read", "incident.avariya.read",
    ],
    "ombor_mudiri": [
        "request.issue", "stock.read", "stock.write", "card.read",
        "report.read", "report.download",
        "incident.tb.read", "incident.avariya.read",
    ],
    "yoriqchi": [
        "kip.read", "kip.write", "talon.read", "journal.read",
        "report.read", "report.download",
        "incident.avariya.write", "incident.avariya.read", "incident.tb.read",
    ],
    "sex_boshligi": [
        "journal.read", "card.read", "stock.read", "talon.read", "kip.read",
        "incident.tb.read", "incident.avariya.read",
    ],
    "ishchi": [
        "request.create", "request.receive", "card.read", "talon.read", "kip.read",
        "incident.tb.read", "incident.avariya.read",
    ],
}


# ---------------------------------------------------------------------
# Koʻrinish (feature) kalitlari
# ---------------------------------------------------------------------

ALL_CARDS: list[str] = [
    "card.mehnat", "card.ombor", "card.faolIshchilar",
    "card.buyumTuri", "card.choraTadbir", "card.kip",
]
ALL_NAV: list[str] = [
    "nav.tb", "nav.ombor", "nav.kip", "nav.talon",
    "nav.hisobot", "nav.arizalar", "nav.hujjatlar", "nav.arxiv",
]
ALL_DOCS: list[str] = ["doc.trebovanie", "doc.mb6", "doc.kitobcha"]

ALL_FEATURES: list[str] = [*ALL_CARDS, *ALL_NAV, *ALL_DOCS]

FEATURE_LABEL: dict[str, str] = {
    "card.mehnat": "Karta: Mehnat muhofazasi jamoatchilik nazorati",
    "card.ombor": "Karta: Omborxona",
    "card.faolIshchilar": "Karta: Faol ishchilar",
    "card.buyumTuri": "Karta: Ombordagi buyum turlari",
    "card.choraTadbir": "Karta: Bajarilishi kutilayotgan chora-tadbirlar",
    "card.kip": "Karta: KIP — muddati yaqin/oʻtgan",
    "nav.tb": "Boʻlim: TB — Nazorat jurnallari",
    "nav.ombor": "Boʻlim: Omborxona",
    "nav.kip": "Boʻlim: KIP — Yoʻriqchi",
    "nav.talon": "Boʻlim: Talonlar va TB imtixoni",
    "nav.hisobot": "Boʻlim: Hisobotlar",
    "nav.arizalar": "Boʻlim: Arizalar",
    "nav.hujjatlar": "Boʻlim: Hujjatlar (tabel qidiruv)",
    "nav.arxiv": "Boʻlim: Hujjatlar arxivi",
    "doc.trebovanie": "Hujjat: Требование (MU-27)",
    "doc.mb6": "Hujjat: MB-6 kartochka",
    "doc.kitobcha": "Hujjat: TB jamoatchilik nazorati kitobchasi",
}

ROLE_FEATURES: dict[str, list[str]] = {
    "admin": list(ALL_FEATURES),
    "depo_boshligi": list(ALL_FEATURES),
    "bosh_xisobchi": list(ALL_FEATURES),
    "sex_boshligi": list(ALL_FEATURES),
    "bugalter": [
        "card.mehnat", "card.choraTadbir",
        "nav.ombor", "nav.hisobot", "nav.arizalar", "nav.hujjatlar",
        *ALL_DOCS,
    ],
    "tb_xodim": [
        *ALL_CARDS,
        "nav.tb", "nav.ombor", "nav.talon", "nav.hisobot", "nav.arizalar", "nav.hujjatlar",
        *ALL_DOCS,
    ],
    "ombor_mudiri": [
        "card.ombor", "card.buyumTuri",
        "nav.ombor", "nav.hisobot", "nav.arizalar", "nav.hujjatlar",
        *ALL_DOCS,
    ],
    "yoriqchi": [
        "card.kip",
        "nav.kip", "nav.hisobot", "nav.arizalar", "nav.hujjatlar",
        *ALL_DOCS,
    ],
    "ishchi": ["nav.arizalar", *ALL_DOCS],
}


# ---------------------------------------------------------------------
# Hisoblash
# ---------------------------------------------------------------------

def role_default(role: str, key: str, is_feature: bool) -> bool:
    if is_feature:
        return key in ROLE_FEATURES.get(role, [])
    return key in ROLE_PERMS.get(role, [])


def load_overrides() -> dict[str, dict[str, dict[str, bool]]]:
    """
    AccessOverride jadvalini frontend kutayotgan koʻrinishga yigʻadi:
        {roleOverrides: {...}, positionOverrides: {...}, userOverrides: {...}}
    """
    from core.models import AccessOverride

    out: dict[str, dict[str, dict[str, bool]]] = {
        "roleOverrides": {},
        "positionOverrides": {},
        "userOverrides": {},
    }
    bucket = {
        "role": "roleOverrides",
        "position": "positionOverrides",
        "user": "userOverrides",
    }
    for row in AccessOverride.objects.all():
        target = out[bucket[row.scope]].setdefault(row.scope_id, {})
        target[row.key] = row.value
    return out


def resolve_access(
    key: str,
    roles: list[str],
    uid: str | None,
    access: dict | None,
    is_feature: bool,
    position_ids: list[str] | None = None,
) -> bool:
    """
    Yakuniy ruxsat/koʻrinishni hisoblaydi.
    lib/permissions.ts → resolveAccess bilan bir xil natija berishi shart.
    """
    if "admin" in (roles or []):
        return True

    access = access or {}

    user_ov = (access.get("userOverrides") or {}).get(uid or "")
    if user_ov and key in user_ov:
        return bool(user_ov[key])

    pos_ov = access.get("positionOverrides") or {}
    for pid in position_ids or []:
        po = pos_ov.get(pid)
        if po and key in po:
            return bool(po[key])

    role_ov = access.get("roleOverrides") or {}
    for r in roles or []:
        ro = role_ov.get(r)
        if ro and key in ro:
            if ro[key]:
                return True
            continue          # shu rol uchun yopilgan — boshqa rolni tekshiramiz
        if role_default(r, key, is_feature):
            return True
    return False


def worker_can(worker, key: str, is_feature: bool = False, access: dict | None = None) -> bool:
    """Ishchi uchun ruxsatni tekshirish — view'larda shu ishlatiladi."""
    if worker is None:
        return False
    if access is None:
        access = load_overrides()
    return resolve_access(
        key,
        worker.roles or [],
        str(worker.id),
        access,
        is_feature,
        worker.position_ids(),
    )


# ---------------------------------------------------------------------
# DRF ruxsat sinfi
# ---------------------------------------------------------------------

class HasPerm(BasePermission):
    """
    View'da shunday ishlatiladi:

        class MyView(APIView):
            permission_classes = [HasPerm]
            perm = "stock.write"
    """

    message = "Bu amal uchun ruxsatingiz yoʻq"

    def has_permission(self, request, view) -> bool:
        worker = request.user
        if not worker or not getattr(worker, "is_authenticated", False):
            return False

        perm = getattr(view, "perm", None)
        if not perm:
            return True

        return worker_can(worker, perm, is_feature=False)


class IsAdmin(BasePermission):
    message = "Faqat administrator uchun"

    def has_permission(self, request, view) -> bool:
        worker = request.user
        return bool(worker and getattr(worker, "is_authenticated", False) and worker.has_role("admin"))
