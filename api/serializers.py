"""
=====================================================================
Serializerlar — Django modellarini frontend kutayotgan shaklga oʻgiradi.

Asosiy vazifa: build_state() funksiyasi lib/types.ts dagi `DB`
interfeysining AYNAN oʻzini qaytaradi. Shu tufayli barcha sahifalar
(db.workers, db.requests, db.stock ...) hech qanday oʻzgarishsiz
ishlashda davom etadi — lekin maʼlumot endi real jadvallardan keladi.

Ikkita ataylab qilingan farq (xavfsizlik va hajm sababli):

  • pinHash  — MIJOZGA UMUMAN YUBORILMAYDI. Oʻrniga `pinSet: bool`.
               PIN endi faqat serverda tekshiriladi.
  • faceImage — bazadagi base64 surat javobga qoʻshilmaydi (800 ta
               ishchi = yuzlab MB). Oʻrniga `faceUrl` beriladi.
=====================================================================
"""

from __future__ import annotations

import re
from decimal import Decimal

from core import permissions as perms
from core.models import (
    AuditLog, Card, Depo, Incident, Item, JournalEntry, Kip, Line,
    Norm, Notification, Position, Request, Signature, Stock, StockMove,
    Talon, Unit, Worker,
)


# ---------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------

def num(v) -> float | int:
    """Decimal → JSON raqami. Butun boʻlsa int, aks holda float."""
    if v is None:
        return 0
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def d(v) -> str | None:
    """date → 'YYYY-MM-DD'"""
    return v.isoformat() if v else None


def dt(v) -> str | None:
    """datetime → ISO satr"""
    return v.isoformat() if v else None


def sid(v) -> str | None:
    """UUID → satr"""
    return str(v) if v else None


def loko_turi(nomi: str | None) -> str:
    """Lavozim nomidan lokomotiv turi: 'elektrovoz' | 'teplovoz' | 'boshqa'.

    KIP roʻyxati (frontend) shu tur boʻyicha ikkita jadvalga ajraladi —
    «Elektrovoz mashinisti va yordamchisi» va «Teplovoz mashinisti va
    yordamchisi». Tur bazada saqlanmaydi, chunki u lavozim nomidan kelib
    chiqadi: yangi lavozim qoʻshilsa ham migratsiya kerak emas.

    Lavozimlar qoʻlda kiritilgani uchun imlo har xil: «elektravoz/teplavoz»,
    kirillcha «электровоз», kolonna jadvalidagi «El. mashinist» — hammasi
    hisobga olinadi. Frontenddagi `positionTuri()` bilan bir xil ishlaydi.
    """
    s = re.sub(r"\s+", " ", re.sub(r"[-–—._/]+", " ", re.sub(r"[ʻʼ’‘`´']", "", (nomi or "").lower()))).strip()
    if not s:
        return "boshqa"
    if re.search(r"elektr[oa]voz|электровоз|\bel mashinist", s):
        return "elektrovoz"
    if re.search(r"tepl[oa]voz|тепловоз", s):
        return "teplovoz"
    return "boshqa"


# ---------------------------------------------------------------------
# Alohida obyektlar
# ---------------------------------------------------------------------

def depo_json(depo: Depo) -> dict:
    return {
        "id": sid(depo.id),
        "kod": depo.kod,
        "nomi": depo.nomi,
        "tashkilot": depo.tashkilot,
        "qishBoshi": depo.qish_boshi,
        "qishOxiri": depo.qish_oxiri,
    }


def position_json(p: Position) -> dict:
    return {
        "id": sid(p.id),
        "tartib": p.tartib,
        "nomi": p.nomi,
        "arxiv": p.arxiv,
        "turi": loko_turi(p.nomi),
    }


def item_json(i: Item) -> dict:
    return {
        "id": sid(i.id),
        "nomi": i.nomi,
        "kod": i.kod,
        "unit": i.unit,
        "qishki": i.qishki,
        "narx": num(i.narx),
        "arxiv": i.arxiv,
    }


def norm_json(n: Norm) -> dict:
    return {
        "id": sid(n.id),
        "positionId": sid(n.position_id),
        "itemId": sid(n.item_id),
        "muddatOy": n.muddat_oy,
        "qishki": n.qishki,
    }


def worker_json(w: Worker, position_ids: list[str] | None = None) -> dict:
    """
    DIQQAT: pin_hash, face_image va face_vector bu yerga QOʻSHILMAYDI.
    Ular hech qachon mijozga yuborilmaydi — faqat "bor/yoʻq" bayrogʻi.
    """
    if position_ids is None:
        position_ids = [str(p.id) for p in w.positions.all()]
        if not position_ids and w.position_id:
            position_ids = [str(w.position_id)]

    return {
        "id": sid(w.id),
        "tabel": w.tabel,
        "familiya": w.familiya,
        "ism": w.ism,
        "otasi": w.otasi,
        "positionId": position_ids[0] if position_ids else "",
        "positionIds": position_ids,
        "sex": w.sex,
        "ishJoyi": w.ish_joyi,
        "kolonna": w.kolonna,
        "kirganSana": d(w.kirgan_sana),
        "jinsi": w.jinsi,
        "boyi": w.boyi,
        "kiyimOlchami": w.kiyim_olchami,
        "poyabzalOlchami": w.poyabzal_olchami,
        "boshKiyimOlchami": w.bosh_kiyim_olchami,
        "telefon": w.telefon,
        "roles": w.roles or [],
        "yoriqchiId": sid(w.yoriqchi_id),
        "faol": w.faol,
        "imzoId": w.imzo_id,
        # Xavfsiz almashtirishlar
        "pinSet": bool(w.pin_hash),
        "pinReset": w.pin_reset,
        "faceUrl": f"/api/v1/workers/{w.id}/face" if (w.rasm or w.face_image) else None,
        # Face ID sozlanganmi (vektor bor) — suratning oʻzi emas
        "faceBor": bool(w.face_vector),
        "royxatdanOtgan": dt(w.royxatdan_otgan),
    }


def signature_json(s: Signature) -> dict:
    # Imzo — hujjatdagi qatʼiy iz: kim, qaysi lavozimda va qachon
    # tasdiqlagani imzo qoʻyilgan PAYTDAGI holicha saqlanadi. Shuning
    # uchun F.I.Sh. ishchi jadvalidan emas, payload'dan olinadi —
    # keyinchalik lavozim oʻzgarsa ham hujjat oʻzgarmaydi.
    payload = s.payload or {}
    fio = payload.get("fio") or (s.user.fio if s.user else "")
    lavozim = payload.get("lavozim") or (
        s.user.position.nomi if (s.user and s.user.position) else ""
    )
    return {
        "id": sid(s.id),
        "docType": s.doc_type,
        "docId": s.doc_id,
        "field": s.field,
        "userId": sid(s.user_id),
        "sana": dt(s.sana),
        "hash": s.hash,
        "fio": fio,
        "lavozim": lavozim,
    }


def card_json(c: Card) -> dict:
    return {
        "id": sid(c.id),
        "workerId": sid(c.worker_id),
        "ochilgan": d(c.ochilgan),
        "berilgan": [
            {
                "id": sid(b.id),
                "itemId": sid(b.item_id),
                "sana": d(b.sana),
                "soni": num(b.soni),
                "yaroqlilik": b.yaroqlilik,
                "imzoId": b.imzo_id or None,
            }
            for b in c.berilgan.all()
        ],
        "qaytarilgan": [
            {
                "id": sid(q.id),
                "itemId": sid(q.item_id),
                "sana": d(q.sana),
                "soni": num(q.soni),
                "yaroqlilik": q.yaroqlilik,
                "ishchiImzoId": q.ishchi_imzo_id or None,
                "omborImzoId": q.ombor_imzo_id or None,
            }
            for q in c.qaytarilgan.all()
        ],
        "imzolar": {},
    }


def request_json(r: Request, imzolar: dict[str, list] | None = None) -> dict:
    sigs = (imzolar or {}).get(str(r.id), [])
    return {
        "id": sid(r.id),
        "raqam": r.raqam,
        "workerId": sid(r.worker_id),
        "turi": r.turi,
        "status": r.status,
        "lines": [
            {
                "itemId": sid(l.item_id),
                "soni": num(l.soni),
                "unit": l.unit,
                "narx": num(l.narx),
            }
            for l in r.lines.all()
        ],
        "yaratganId": sid(r.yaratgan_id),
        "yaratilgan": d(r.yaratilgan),
        "yakunlangan": d(r.yakunlangan),
        "transitions": [
            {
                "from": t.from_status,
                "to": t.to_status,
                "userId": sid(t.user_id),
                "sana": dt(t.sana),
                "izoh": t.izoh or None,
            }
            for t in r.transitions.all()
        ],
        "imzolar": [signature_json(s) for s in sigs],
        "bugField": r.bug_field or {},
    }


def journal_json(j: JournalEntry) -> dict:
    return {
        "id": sid(j.id),
        "bosqich": j.bosqich,
        "sana": d(j.sana),
        "komissiya": j.komissiya or [],
        "nomuvofiqlik": j.nomuvofiqlik,
        "chora": j.chora,
        "masul": j.masul,
        "masulLavozim": j.masul_lavozim,
        "muddat": d(j.muddat),
        "bajarildi": j.bajarildi,
        "bajarilganIzoh": j.bajarilgan_izoh or None,
        "imzo": signature_json(j.imzo) if j.imzo else None,
    }


def stock_json(s: Stock) -> dict:
    return {"itemId": sid(s.item_id), "qoldiq": num(s.qoldiq)}


def move_json(m: StockMove) -> dict:
    return {
        "id": sid(m.id),
        "itemId": sid(m.item_id),
        "turi": m.turi,
        "soni": num(m.soni),
        "sana": d(m.sana),
        "izoh": m.izoh,
        "hujjatId": m.hujjat_id or None,
    }


def talon_json(t: Talon) -> dict:
    return {
        "workerId": sid(t.worker_id),
        "raqam": t.raqam,
        "olingan": t.olingan,
        "tarix": [
            {
                "amal": h.amal,
                "sana": dt(h.sana),
                "tbXodimId": sid(h.tb_xodim_id),
                "sabab": h.sabab or None,
            }
            for h in t.tarix.all()
        ],
    }


def exam_json(e) -> dict:
    return {
        "workerId": sid(e.worker_id),
        "oxirgi": d(e.oxirgi),
        "davriylikOy": e.davriylik_oy,
        "natija": e.natija,
    }


def kip_json(k: Kip) -> dict:
    return {
        "id": sid(k.id),
        "workerId": sid(k.worker_id),
        "yoriqchiId": sid(k.yoriqchi_id),
        "liniya": k.liniya,
        "sana": d(k.sana),
        "muddatOy": k.muddat_oy,
        "tugash": d(k.tugash),
        "imzoId": k.imzo_id or None,
    }


def notification_json(n: Notification) -> dict:
    return {
        "id": sid(n.id),
        "workerId": sid(n.worker_id),
        "turi": n.turi,
        "sarlavha": n.sarlavha,
        "matn": n.matn,
        "sana": dt(n.sana),
        "oqilgan": n.oqilgan,
    }


def incident_json(i: Incident) -> dict:
    return {
        "id": sid(i.id),
        "turi": i.turi,
        "matn": i.matn,
        "authorId": sid(i.author_id),
        "sana": dt(i.sana),
    }


def audit_json(a: AuditLog) -> dict:
    return {
        "id": sid(a.id),
        "userId": sid(a.user_id),
        "obyekt": a.obyekt,
        "amal": a.amal,
        "sana": dt(a.sana),
        "izoh": a.izoh or None,
    }


# ---------------------------------------------------------------------
# Butun holat — GET /api/v1/state
# ---------------------------------------------------------------------

def build_state(me: Worker | None = None) -> dict:
    """
    Frontend'dagi `DB` obyektini real jadvallardan yigʻadi.

    Barcha bogʻliqliklar oldindan yuklanadi (prefetch) — 800 ishchi
    boʻlsa ham soʻrovlar soni doimiy qoladi, N+1 muammosi yoʻq.
    """
    depo = Depo.joriy()

    # --- ishchilar (lavozimlari bilan) ---
    workers_qs = (
        Worker.objects.filter(deleted=False)
        .prefetch_related("positions")
        .order_by("familiya", "ism")
    )
    workers = []
    for w in workers_qs:
        pids = [str(p.id) for p in w.positions.all()]
        if not pids and w.position_id:
            pids = [str(w.position_id)]
        workers.append(worker_json(w, pids))

    # --- arizalar va ularning imzolari ---
    requests_qs = (
        Request.objects.all()
        .prefetch_related("lines", "transitions")
        .order_by("-created_at")
    )
    req_ids = [str(r.id) for r in requests_qs]
    imzolar: dict[str, list] = {}
    if req_ids:
        # user/position ham birga olinadi — signature_json ularga murojaat
        # qiladi, aks holda har imzo uchun alohida soʻrov ketardi (N+1).
        for s in Signature.objects.filter(
            doc_type="requisition", doc_id__in=req_ids, bekor=False
        ).select_related("user__position"):
            imzolar.setdefault(s.doc_id, []).append(s)

    # --- kartochkalar ---
    cards_qs = Card.objects.all().prefetch_related("berilgan", "qaytarilgan")

    # --- talonlar ---
    talons_qs = Talon.objects.all().prefetch_related("tarix").order_by("raqam")

    from core.models import Exam

    return {
        "depo": depo_json(depo),
        "positions": [position_json(p) for p in Position.objects.filter(depo=depo)],
        "items": [item_json(i) for i in Item.objects.all()],
        "norms": [norm_json(n) for n in Norm.objects.all()],
        "workers": workers,
        "cards": [card_json(c) for c in cards_qs],
        "requests": [request_json(r, imzolar) for r in requests_qs],
        "journal": [
            journal_json(j)
            for j in JournalEntry.objects.select_related("imzo__user__position")
        ],
        "stock": [stock_json(s) for s in Stock.objects.all()],
        "moves": [move_json(m) for m in StockMove.objects.all()[:500]],
        "talons": [talon_json(t) for t in talons_qs],
        "exams": [exam_json(e) for e in Exam.objects.all()],
        "kips": [kip_json(k) for k in Kip.objects.all()],
        "notifications": [notification_json(n) for n in Notification.objects.all()[:200]],
        "incidents": [incident_json(i) for i in Incident.objects.all()],
        "audit": [audit_json(a) for a in AuditLog.objects.all()[:400]],
        "lines": list(Line.objects.values_list("nomi", flat=True)),
        "units": list(Unit.objects.values_list("nomi", flat=True)),
        "access": perms.load_overrides(),
        "seq": depo.seq,
    }


# ---------------------------------------------------------------------
# Kirgan foydalanuvchi — GET /api/v1/me
# ---------------------------------------------------------------------

def me_json(w: Worker) -> dict:
    """Joriy foydalanuvchi + uning hisoblangan ruxsatlari."""
    access = perms.load_overrides()
    pids = w.position_ids()
    roles = w.roles or []

    return {
        **worker_json(w, pids),
        "fio": w.fio,
        "perms": [
            p for p in perms.ALL_PERMS
            if perms.resolve_access(p, roles, str(w.id), access, False, pids)
        ],
        "features": [
            f for f in perms.ALL_FEATURES
            if perms.resolve_access(f, roles, str(w.id), access, True, pids)
        ],
    }
