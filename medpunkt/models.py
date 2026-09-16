"""
=====================================================================
Med-punkt (METROBOT kiosk) — domen modellari.

Kiosk depoda turadi: xodim QR kartasini skanerlaydi, yuzi tekshiriladi,
soʻng alkotester va tonometrdan oʻtadi. Kiosk faqat XOM oʻlchovni
yuboradi — «meʼyorda / meʼyordan chetda» qarorini SERVER hisoblaydi
(`medpunkt/logic.py`). Shu sabab kioskdagi sozlamani oʻzgartirib
xulosani soxtalashtirib boʻlmaydi.

Bu ilova `core`/`api` ga aralashmaydi — faqat `core.Worker` ga
ForeignKey qoʻyadi. Jadvallari: `medpunkt_*`.

Maxfiylik: kiosk serverga surat ham, yuz vektorini ham yubormaydi —
faqat oʻlchov natijasi, tabel raqami va tasdiq belgilari.
=====================================================================
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------
# Sanoq roʻyxatlari
# ---------------------------------------------------------------------

TURLAR = [
    ("alko", "Alkotester"),
    ("qon", "Qon bosimi"),
]

HOLATLAR = [
    ("normal", "Meʼyorda"),
    ("flagged", "Meʼyordan chetda"),
    ("egasiz", "Xodim aniqlanmagan"),
]

HODISA_TURLAR = [
    ("timeout", "Vaqt tugadi"),
    ("qr_xato", "QR oʻqilmadi"),
    ("face_xato", "Yuz tasdiqlanmadi"),
    ("qurilma_xato", "Qurilma xatosi"),
    ("limit", "12 soatlik chegara"),
    ("boshqa", "Boshqa"),
]


class Base(models.Model):
    """Ilovaning umumiy asosi — UUID kalit va yaratilgan vaqt (core bilan bir xil)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------
# Med-punkt — bitta kiosk (bitta depoda bir nechta boʻlishi mumkin)
# ---------------------------------------------------------------------

class MedPunkt(Base):
    """
    Kiosk oʻzini `kod` bilan tanishtiradi (masalan `BUX-1`). Notanish kod
    kelsa yozuv avtomatik ochiladi — mas'ul serverga qoʻl tegizmaydi.
    """

    kod = models.CharField(max_length=32, unique=True, verbose_name="Kod")
    nom = models.CharField(max_length=128, blank=True, verbose_name="Nomi")
    faol = models.BooleanField(default=True)
    oxirgi_aloqa = models.DateTimeField(
        null=True, blank=True, help_text="Kiosk oxirgi marta murojaat qilgan payt"
    )

    class Meta:
        verbose_name = "Med-punkt"
        verbose_name_plural = "Med-punktlar"
        ordering = ["kod"]

    def __str__(self) -> str:
        return self.nom or self.kod


# ---------------------------------------------------------------------
# Umumiy chegaralar — bitta yozuv
# ---------------------------------------------------------------------

class Sozlama(Base):
    """
    Butun tizim uchun umumiy chegaralar. Shaxsiy meʼyori bor xodimga
    `IshchiMeyor` qoʻllanadi, qolganlarga — shu.

    Alkotester chegarasi ikkita: aktiv (naycha bilan puflash) va passiv
    (naychasiz) rejim uchun — passiv rejimda havo suyuladi, shuning
    uchun uning chegarasi pastroq.
    """

    alko_chegara_mg_l = models.FloatField(
        default=0.135, verbose_name="Alko chegara (aktiv), mg/L"
    )
    alko_chegara_passiv_mg_l = models.FloatField(
        default=0.023, verbose_name="Alko chegara (passiv), mg/L"
    )

    qon_sis_max = models.IntegerField(default=140, verbose_name="Sistolik maksimum")
    qon_dia_max = models.IntegerField(default=90, verbose_name="Diastolik maksimum")
    qon_puls_min = models.IntegerField(default=50, verbose_name="Puls minimum")
    qon_puls_max = models.IntegerField(default=110, verbose_name="Puls maksimum")

    limit_12_soat = models.IntegerField(
        default=5, verbose_name="12 soatda ruxsat etilgan koʻrik"
    )
    arxiv_kun = models.IntegerField(default=7, verbose_name="Arxivga oʻtish (kun)")

    yangilandi = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chegaralar"
        verbose_name_plural = "Chegaralar"

    def __str__(self) -> str:
        return "Med-punkt chegaralari"

    @classmethod
    def joriy(cls) -> "Sozlama":
        """Yagona sozlama yozuvi — boʻlmasa standart qiymatlar bilan ochiladi."""
        obj = cls.objects.order_by("created_at").first()
        if obj is None:
            obj = cls.objects.create()
        return obj


# ---------------------------------------------------------------------
# Shaxsiy meʼyor — shifokor kiritadi
# ---------------------------------------------------------------------

class IshchiMeyor(Base):
    """
    Surunkali gipertoniya kabi holatlarda shifokor xodimga shaxsiy
    chegara belgilaydi. Bunday xodimga umumiy `Sozlama` emas, shu
    qiymatlar qoʻllanadi. Bitta xodimga bitta yozuv.
    """

    worker = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="medpunkt_meyor"
    )

    sis_max = models.IntegerField(default=140)
    dia_max = models.IntegerField(default=90)
    puls_min = models.IntegerField(default=50)
    puls_max = models.IntegerField(default=110)

    izoh = models.CharField(max_length=255, blank=True)
    shifokor = models.CharField(
        max_length=128, blank=True, help_text="Meʼyorni kiritgan xodim"
    )
    yangilandi = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Shaxsiy meʼyor"
        verbose_name_plural = "Shaxsiy meʼyorlar"
        ordering = ["worker__familiya", "worker__ism"]

    def __str__(self) -> str:
        return f"{self.worker.tabel} — {self.sis_max}/{self.dia_max}"


# ---------------------------------------------------------------------
# Oʻlchov — kioskdan kelgan bitta natija
# ---------------------------------------------------------------------

class Olchov(Base):
    """
    Bitta oʻlchov: yo alkotester, yo tonometr natijasi.

    `unik_kalit` — qurilmaning oʻz yozuv identifikatori (masalan
    `A604070|56|2026/09/13|11:06:47|0`). UNIQUE: kiosk aloqa uzilganda
    buferdagi oʻlchovni qayta yuborsa, yangi yozuv YARATILMAYDI
    (idempotent).

    `holat` va `izoh` — SERVER xulosasi, kiosk ularni yubormaydi.
    """

    med_punkt = models.ForeignKey(
        MedPunkt, on_delete=models.CASCADE, related_name="olchovlar"
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="medpunkt_olchovlari",
        help_text="Tabel boʻyicha topilgan xodim (topilmasa — boʻsh)",
    )

    tabel = models.CharField(
        max_length=32, blank=True, db_index=True, help_text="Kioskdagi tabel/karta ID"
    )
    sessiya_id = models.CharField(max_length=64, blank=True, db_index=True)

    tur = models.CharField(max_length=8, choices=TURLAR)
    qurilma = models.CharField(max_length=64, blank=True, help_text="Model/seriya raqami")
    unik_kalit = models.CharField(max_length=128, unique=True)
    olchov_vaqti = models.DateTimeField(db_index=True)

    qiymatlar = models.JSONField(
        default=dict, help_text="Xom natija: mg_l/aktiv yoki sistolik/diastolik/puls"
    )
    tasdiq = models.JSONField(
        default=dict, help_text="{qr, face, surat} — tekshirilmagan boʻlsa null"
    )
    face_masofa = models.FloatField(null=True, blank=True)

    egasiz = models.BooleanField(
        default=False, help_text="Sessiyasiz (QR skanersiz) oʻlchov"
    )
    holat = models.CharField(
        max_length=8, choices=HOLATLAR, default="normal", db_index=True
    )
    izoh = models.CharField(max_length=255, blank=True, help_text="Server xulosasi")

    arxivlangan = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Oʻlchov"
        verbose_name_plural = "Oʻlchovlar"
        ordering = ["-olchov_vaqti"]

    def __str__(self) -> str:
        kim = self.worker.tabel if self.worker else (self.tabel or "aniqlanmagan")
        return f"{kim} — {self.get_tur_display()} — {self.get_holat_display()}"


# ---------------------------------------------------------------------
# Hodisa — oʻlchovga yetib bormagan holatlar
# ---------------------------------------------------------------------

class Hodisa(Base):
    """
    Kioskda koʻrik yakunlanmagan hollar: vaqt tugashi, QR oʻqilmasligi,
    yuz tasdiqlanmasligi, qurilma xatosi. Mas'ul «Koʻrildi» bilan yopadi.
    """

    med_punkt = models.ForeignKey(
        MedPunkt, on_delete=models.CASCADE, related_name="hodisalar"
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="medpunkt_hodisalari",
    )

    tur = models.CharField(max_length=32, db_index=True)
    tabel = models.CharField(max_length=32, blank=True)
    sessiya_id = models.CharField(max_length=64, blank=True)
    tafsilot = models.CharField(max_length=255, blank=True)
    vaqt = models.DateTimeField(db_index=True)
    korildi = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Kiosk hodisasi"
        verbose_name_plural = "Kiosk hodisalari"
        ordering = ["-vaqt"]

    def __str__(self) -> str:
        return f"{self.tur} — {self.tabel or '—'}"
