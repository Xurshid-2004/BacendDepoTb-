"""
=====================================================================
Med-punkt — JSON koʻrinishlari.

Bazada maydonlar snake_case, frontend esa camelCase kutadi
(`app/(sys)/medpunkt/page.tsx`). Oʻgirish shu yerda, bir joyda.
=====================================================================
"""

from __future__ import annotations

from medpunkt.models import Hodisa, IshchiMeyor, MedPunkt, Olchov, Sozlama


def dt(v) -> str | None:
    """datetime → ISO satr"""
    return v.isoformat() if v else None


def worker_qisqa(w) -> dict | None:
    """
    Panel jadvali uchun xodimning eng kam maʼlumoti. Surat, PIN, yuz
    vektori — hech qachon bu yerdan chiqmaydi.
    """
    if w is None:
        return None
    return {
        "id": str(w.id),
        "fio": w.fio,
        "tabel": w.tabel,
        "kolonna": w.kolonna_ref.nomi if w.kolonna_ref_id else (w.kolonna or ""),
        "kolonnaId": str(w.kolonna_ref_id) if w.kolonna_ref_id else None,
    }


def punkt_json(p: MedPunkt) -> dict:
    return {
        "id": str(p.id),
        "kod": p.kod,
        "nom": p.nom,
        "faol": p.faol,
        "oxirgiAloqa": dt(p.oxirgi_aloqa),
    }


def olchov_json(o: Olchov) -> dict:
    return {
        "id": str(o.id),
        "medPunkt": o.med_punkt.kod,
        "medPunktNom": o.med_punkt.nom,
        "qurilma": o.qurilma,
        "worker": worker_qisqa(o.worker),
        "tabel": o.tabel,
        "sessiyaId": o.sessiya_id,
        "tur": o.tur,
        "olchovVaqti": dt(o.olchov_vaqti),
        "qiymatlar": o.qiymatlar or {},
        "tasdiq": o.tasdiq or {},
        "faceMasofa": o.face_masofa,
        "holat": o.holat,
        "izoh": o.izoh,
        "unikKalit": o.unik_kalit,
        "arxivlangan": o.arxivlangan,
    }


def hodisa_json(h: Hodisa) -> dict:
    return {
        "id": str(h.id),
        "medPunkt": h.med_punkt.kod,
        "tur": h.tur,
        "worker": worker_qisqa(h.worker),
        "tabel": h.tabel,
        "sessiyaId": h.sessiya_id,
        "tafsilot": h.tafsilot,
        "vaqt": dt(h.vaqt),
        "korildi": h.korildi,
    }


def meyor_json(m: IshchiMeyor) -> dict:
    return {
        "workerId": str(m.worker_id),
        "tabel": m.worker.tabel,
        "fio": m.worker.fio,
        "sisMax": m.sis_max,
        "diaMax": m.dia_max,
        "pulsMin": m.puls_min,
        "pulsMax": m.puls_max,
        "izoh": m.izoh,
        "shifokor": m.shifokor,
        "yangilandi": dt(m.yangilandi),
    }


def sozlama_json(s: Sozlama) -> dict:
    return {
        "alkoChegaraMgL": s.alko_chegara_mg_l,
        "alkoChegaraPassivMgL": s.alko_chegara_passiv_mg_l,
        "qonSisMax": s.qon_sis_max,
        "qonDiaMax": s.qon_dia_max,
        "qonPulsMin": s.qon_puls_min,
        "qonPulsMax": s.qon_puls_max,
        "limit12Soat": s.limit_12_soat,
        "arxivKun": s.arxiv_kun,
        "yangilandi": dt(s.yangilandi),
    }
