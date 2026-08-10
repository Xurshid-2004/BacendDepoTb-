"""
=====================================================================
TB tizimi — domen modellari

Bu modellar frontend'dagi lib/types.ts (DB interfeysi) bilan bir xil
maʼnoni ifodalaydi, lekin endi maʼlumot real relatsion jadvallarda
saqlanadi — JSON blob emas.

Nomlash: maydonlar Python uslubida (snake_case), API qatlami esa
frontend kutayotgan camelCase'ga oʻgiradi (api/serializers.py).
=====================================================================
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------
# Sanoq roʻyxatlari
# ---------------------------------------------------------------------

ROLES = [
    ("admin", "Administrator"),
    ("depo_boshligi", "Depo boshligʻi"),
    ("bosh_xisobchi", "Bosh xisobchi"),
    ("bugalter", "Bugalter"),
    ("tb_xodim", "TB xodimi"),
    ("ombor_mudiri", "Omborxona mudiri"),
    ("yoriqchi", "Mashinist yoʻriqchisi"),
    ("sex_boshligi", "Sex boʻlimi boshligʻi"),
    ("ishchi", "Ishchi"),
]
ROLE_KEYS = [r[0] for r in ROLES]

REQUEST_STATUS = [
    ("DRAFT", "Qoralama"),
    ("SUBMITTED", "Bugalterda"),
    ("ACCOUNTANT_APPROVED", "Bosh xisobchida"),
    ("CHIEF_APPROVED", "Depo boshligʻida"),
    ("HEAD_APPROVED", "Omborda"),
    ("ISSUED", "Berildi — ishchi tasdigʻi kutilmoqda"),
    ("RECEIVED", "Olindi — ombor tasdigʻi kutilmoqda"),
    ("COMPLETED", "Yakunlandi"),
    ("REJECTED", "Rad etildi"),
]

DOC_TYPES = [
    ("journal", "Jurnal"),
    ("requisition", "Требование"),
    ("card", "Kartochka"),
    ("kip", "KIP"),
]


class Base(models.Model):
    """Barcha modellar uchun umumiy asos — UUID kalit va yaratilgan vaqt."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------
# Depo — bitta oʻrnatma bitta depoga xizmat qiladi
# ---------------------------------------------------------------------

class Depo(Base):
    kod = models.CharField(max_length=32, unique=True)
    nomi = models.CharField(max_length=255)
    tashkilot = models.CharField(max_length=255, blank=True)
    qish_boshi = models.CharField(max_length=5, default="09-15", help_text="MM-DD")
    qish_oxiri = models.CharField(max_length=5, default="04-15", help_text="MM-DD")

    # Ariza raqamlari ketma-ketligi (TCH6-YYYY-NNNNN)
    seq = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Depo"
        verbose_name_plural = "Depolar"

    def __str__(self) -> str:
        return f"{self.kod} — {self.nomi}"

    @classmethod
    def joriy(cls) -> "Depo":
        """Sozlamadagi depo kodi boʻyicha joriy depo (boʻlmasa — yaratiladi)."""
        depo, _ = cls.objects.get_or_create(
            kod=settings.DEPO_KOD,
            defaults={
                "nomi": f"{settings.DEPO_KOD} lokomotiv deposi",
                "tashkilot": "OʻTY AJ",
            },
        )
        return depo


class Position(Base):
    """Lavozim — normalar shu boʻyicha belgilanadi."""

    depo = models.ForeignKey(Depo, on_delete=models.CASCADE, related_name="positions")
    tartib = models.IntegerField(default=0)
    nomi = models.CharField(max_length=255)
    arxiv = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Lavozim"
        verbose_name_plural = "Lavozimlar"
        ordering = ["tartib", "nomi"]

    def __str__(self) -> str:
        return self.nomi


class Unit(Base):
    """Oʻlchov birligi (dona, kg, metr, sm, juft ...) — admin qoʻshishi mumkin."""

    nomi = models.CharField(max_length=32, unique=True)
    tartib = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Oʻlchov birligi"
        verbose_name_plural = "Oʻlchov birliklari"
        ordering = ["tartib", "nomi"]

    def __str__(self) -> str:
        return self.nomi


class Line(Base):
    """KIP liniyasi (yoʻnalish) roʻyxati."""

    nomi = models.CharField(max_length=255, unique=True)
    tartib = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Liniya"
        verbose_name_plural = "Liniyalar"
        ordering = ["tartib", "nomi"]

    def __str__(self) -> str:
        return self.nomi


class Item(Base):
    """Buyum (maxsus kiyim / himoya vositasi)."""

    nomi = models.CharField(max_length=255)
    kod = models.CharField(max_length=64, blank=True, help_text="Nomenklatura kodi")
    unit = models.CharField(max_length=32, default="dona")
    qishki = models.BooleanField(default=False)
    narx = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    arxiv = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Buyum"
        verbose_name_plural = "Buyumlar"
        ordering = ["nomi"]

    def __str__(self) -> str:
        return self.nomi


class Norm(Base):
    """Lavozim uchun buyum normasi. muddat_oy = None → "Ish. Chiqqun"."""

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="norms")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="norms")
    muddat_oy = models.IntegerField(null=True, blank=True, help_text="Boʻsh = Ish. Chiqqun")
    qishki = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Norma"
        verbose_name_plural = "Normalar"
        unique_together = [("position", "item")]

    def __str__(self) -> str:
        muddat = "Ish. Chiqqun" if self.muddat_oy is None else f"{self.muddat_oy} oy"
        return f"{self.position.nomi} — {self.item.nomi} ({muddat})"


# ---------------------------------------------------------------------
# Ishchi (foydalanuvchi) — tizimga tabel raqami + PIN bilan kiradi
# ---------------------------------------------------------------------

class WorkerManager(BaseUserManager):
    def create_user(self, tabel: str, pin: str | None = None, **extra):
        if not tabel:
            raise ValueError("Tabel raqami majburiy")
        worker = self.model(tabel=tabel.strip(), **extra)
        worker.set_unusable_password()
        if pin:
            worker.set_pin(pin)
        worker.save(using=self._db)
        return worker

    def create_superuser(self, tabel: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("faol", True)
        extra.setdefault("familiya", "Administrator")
        extra.setdefault("ism", tabel)
        worker = self.model(tabel=tabel.strip(), **extra)
        worker.set_password(password)          # admin panel uchun oddiy parol
        if not worker.roles:
            worker.roles = ["admin"]
        worker.save(using=self._db)
        return worker


class Worker(Base, AbstractBaseUser, PermissionsMixin):
    """
    Ishchi = tizim foydalanuvchisi.

    Ikki xil kirish yoʻli bor:
      • ilova  — tabel raqami + 4 xonali PIN (pin_hash)
      • admin  — Django paroli (password), faqat xodimlar uchun
    """

    depo = models.ForeignKey(Depo, on_delete=models.CASCADE, related_name="workers")

    tabel = models.CharField(max_length=32, unique=True, db_index=True)
    familiya = models.CharField(max_length=128)
    ism = models.CharField(max_length=128)
    otasi = models.CharField(max_length=128, blank=True)

    # Asosiy lavozim — eski kod bilan moslik uchun saqlanadi
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, blank=True, related_name="workers"
    )
    # Barcha lavozimlar (bitta ham, bir nechta ham boʻlishi mumkin)
    positions = models.ManyToManyField(Position, blank=True, related_name="workers_multi")

    sex = models.CharField(max_length=128, blank=True)
    ish_joyi = models.CharField(max_length=255, blank=True)
    kolonna = models.CharField(max_length=64, blank=True)
    kirgan_sana = models.DateField(null=True, blank=True)
    jinsi = models.CharField(max_length=8, default="erkak", choices=[("erkak", "Erkak"), ("ayol", "Ayol")])

    boyi = models.IntegerField(default=0)
    kiyim_olchami = models.CharField(max_length=32, blank=True)
    poyabzal_olchami = models.CharField(max_length=32, blank=True)
    bosh_kiyim_olchami = models.CharField(max_length=32, blank=True)
    telefon = models.CharField(max_length=32, blank=True)

    roles = models.JSONField(default=list, help_text="Rollar roʻyxati")
    yoriqchi = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="biriktirilgan"
    )

    faol = models.BooleanField(default=True)
    imzo_id = models.CharField(max_length=64, blank=True)

    # FaceID — koʻrsatish uchun base64 data URL (admin panelida avatar)
    face_image = models.TextField(blank=True)

    # FaceID — taqqoslash uchun 512 oʻlchovli vektor (InsightFace buffalo_l).
    # Surat emas, aynan shu vektor bilan solishtiriladi. Vektordan asl
    # suratni tiklab boʻlmaydi — shuning uchun uni saqlash xavfsizroq.
    face_vector = models.JSONField(default=list, blank=True)

    # Ishchi oʻzi roʻyxatdan oʻtgan payt (admin qoʻshgani — bu emas)
    royxatdan_otgan = models.DateTimeField(null=True, blank=True)

    # PIN — hech qachon ochiq saqlanmaydi. Format: "saltHex:hashHex"
    pin_hash = models.CharField(max_length=255, blank=True)
    pin_reset = models.BooleanField(default=False, help_text="Keyingi kirishda majburiy yangi PIN")

    # Django admin uchun
    is_staff = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)

    objects = WorkerManager()

    USERNAME_FIELD = "tabel"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "Ishchi"
        verbose_name_plural = "Ishchilar"
        ordering = ["familiya", "ism"]
        indexes = [
            models.Index(fields=["tabel"]),
            models.Index(fields=["faol", "deleted"]),
        ]

    def __str__(self) -> str:
        return f"{self.tabel} — {self.fio}"

    # -- yordamchilar ---------------------------------------------------

    @property
    def fio(self) -> str:
        parts = [self.familiya, self.ism, self.otasi]
        return " ".join(p for p in parts if p).strip()

    @property
    def is_active(self) -> bool:            # Django auth shu nomni kutadi
        return self.faol and not self.deleted

    @is_active.setter
    def is_active(self, value: bool) -> None:
        self.faol = bool(value)

    def has_role(self, *roles: str) -> bool:
        mine = self.roles or []
        return "admin" in mine or any(r in mine for r in roles)

    def position_ids(self) -> list[str]:
        """Barcha lavozim id'lari — koʻp lavozim boʻlsa hammasi."""
        ids = [str(p.id) for p in self.positions.all()]
        if not ids and self.position_id:
            ids = [str(self.position_id)]
        return ids

    # -- PIN ------------------------------------------------------------

    def set_pin(self, pin: str) -> None:
        from core.pin import hash_pin

        self.pin_hash = hash_pin(pin)
        self.pin_reset = False

    def check_pin(self, pin: str) -> bool:
        from core.pin import verify_pin

        return verify_pin(pin, self.pin_hash)

    def clear_pin(self) -> None:
        self.pin_hash = ""
        self.pin_reset = True


# ---------------------------------------------------------------------
# MB-6 kartochka
# ---------------------------------------------------------------------

class Card(Base):
    worker = models.OneToOneField(Worker, on_delete=models.CASCADE, related_name="card")
    ochilgan = models.DateField(default=timezone.localdate)

    class Meta:
        verbose_name = "MB-6 kartochka"
        verbose_name_plural = "MB-6 kartochkalar"

    def __str__(self) -> str:
        return f"Kartochka — {self.worker.fio}"


class CardIssue(Base):
    """Kartochkaga berilgan buyum yozuvi."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="berilgan")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    sana = models.DateField()
    soni = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    yaroqlilik = models.IntegerField(default=100)
    imzo_id = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Berilgan buyum"
        verbose_name_plural = "Berilgan buyumlar"
        ordering = ["-sana"]


class CardReturn(Base):
    """Kartochkaga qaytarilgan buyum yozuvi."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="qaytarilgan")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    sana = models.DateField()
    soni = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    yaroqlilik = models.IntegerField(default=0)
    ishchi_imzo_id = models.CharField(max_length=64, blank=True)
    ombor_imzo_id = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Qaytarilgan buyum"
        verbose_name_plural = "Qaytarilgan buyumlar"
        ordering = ["-sana"]


# ---------------------------------------------------------------------
# Ariza (Требование МУ№27)
# ---------------------------------------------------------------------

class Request(Base):
    raqam = models.CharField(max_length=64, unique=True, db_index=True)
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="requests")
    turi = models.CharField(
        max_length=32,
        default="oddiy",
        choices=[("oddiy", "Oddiy"), ("yangi_ishchi", "Yangi ishchi")],
    )
    status = models.CharField(max_length=32, default="SUBMITTED", choices=REQUEST_STATUS, db_index=True)

    yaratgan = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="yaratgan_requests"
    )
    yaratilgan = models.DateField(default=timezone.localdate)
    yakunlangan = models.DateField(null=True, blank=True)

    # Bugalter qoʻlda toʻldiradigan maydonlar (07/13/16/17/18/19)
    bug_field = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Ariza"
        verbose_name_plural = "Arizalar"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.raqam} — {self.worker.fio}"

    @property
    def summa(self):
        return sum((l.soni * l.narx for l in self.lines.all()), start=0)


class RequestLine(Base):
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    soni = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit = models.CharField(max_length=32, default="dona")
    narx = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Ariza qatori"
        verbose_name_plural = "Ariza qatorlari"


class Transition(Base):
    """Ariza holati oʻzgarishi tarixi."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name="transitions")
    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)
    user = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    sana = models.DateTimeField(default=timezone.now)
    izoh = models.TextField(blank=True)

    class Meta:
        verbose_name = "Holat oʻzgarishi"
        verbose_name_plural = "Holat oʻzgarishlari"
        ordering = ["sana"]


class Signature(Base):
    """Hujjatdagi imzo — QR orqali tekshiriladi."""

    doc_type = models.CharField(max_length=32, choices=DOC_TYPES)
    doc_id = models.CharField(max_length=64, db_index=True)
    field = models.CharField(max_length=16, help_text="Blankadagi maydon raqami")
    user = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    sana = models.DateTimeField(default=timezone.now)
    hash = models.CharField(max_length=64)
    bekor = models.BooleanField(default=False)

    # Blankaga chiqadigan qiymatlar (FIO / lavozim / sana)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Imzo"
        verbose_name_plural = "Imzolar"
        ordering = ["-sana"]
        indexes = [models.Index(fields=["doc_type", "doc_id", "field"])]

    def __str__(self) -> str:
        return f"{self.doc_type}/{self.field} — {self.hash[:8]}"


# ---------------------------------------------------------------------
# TB jurnali (Йў Д-26)
# ---------------------------------------------------------------------

class JournalEntry(Base):
    bosqich = models.IntegerField(choices=[(1, "1-bosqich"), (2, "2-bosqich")])
    sana = models.DateField()
    komissiya = models.JSONField(default=list, blank=True, help_text="[{fio, lavozim}]")
    nomuvofiqlik = models.TextField()
    chora = models.TextField(blank=True)
    masul = models.CharField(max_length=255, blank=True)
    masul_lavozim = models.CharField(max_length=255, blank=True)
    muddat = models.DateField()
    bajarildi = models.BooleanField(default=False)
    bajarilgan_izoh = models.TextField(blank=True)
    imzo = models.ForeignKey(Signature, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Jurnal yozuvi"
        verbose_name_plural = "Jurnal yozuvlari"
        ordering = ["-sana", "-created_at"]

    def __str__(self) -> str:
        return f"{self.bosqich}-bosqich — {self.nomuvofiqlik[:40]}"


# ---------------------------------------------------------------------
# Omborxona
# ---------------------------------------------------------------------

class Stock(Base):
    item = models.OneToOneField(Item, on_delete=models.CASCADE, related_name="stock")
    qoldiq = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Ombor qoldigʻi"
        verbose_name_plural = "Ombor qoldiqlari"

    def __str__(self) -> str:
        return f"{self.item.nomi}: {self.qoldiq}"


class StockMove(Base):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="moves")
    turi = models.CharField(max_length=16, choices=[("kirim", "Kirim"), ("chiqim", "Chiqim")])
    soni = models.DecimalField(max_digits=14, decimal_places=2)
    sana = models.DateField(default=timezone.localdate)
    izoh = models.CharField(max_length=255, blank=True)
    hujjat_id = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Ombor harakati"
        verbose_name_plural = "Ombor harakatlari"
        ordering = ["-sana", "-created_at"]


# ---------------------------------------------------------------------
# Talon / imtixon / KIP
# ---------------------------------------------------------------------

class Talon(Base):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="talons")
    raqam = models.IntegerField(choices=[(1, "1"), (2, "2"), (3, "3")])
    olingan = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Talon"
        verbose_name_plural = "Talonlar"
        unique_together = [("worker", "raqam")]
        ordering = ["raqam"]


class TalonHistory(Base):
    talon = models.ForeignKey(Talon, on_delete=models.CASCADE, related_name="tarix")
    amal = models.CharField(max_length=16, choices=[("olindi", "Olindi"), ("qaytarildi", "Qaytarildi")])
    sana = models.DateTimeField(default=timezone.now)
    tb_xodim = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    sabab = models.TextField(blank=True)

    class Meta:
        verbose_name = "Talon tarixi"
        verbose_name_plural = "Talon tarixi"
        ordering = ["-sana"]


class Exam(Base):
    worker = models.OneToOneField(Worker, on_delete=models.CASCADE, related_name="exam")
    oxirgi = models.DateField()
    davriylik_oy = models.IntegerField(default=12)
    natija = models.CharField(
        max_length=16,
        default="kutilmoqda",
        choices=[("otdi", "Oʻtdi"), ("otmadi", "Oʻtmadi"), ("kutilmoqda", "Kutilmoqda")],
    )

    class Meta:
        verbose_name = "TB imtixoni"
        verbose_name_plural = "TB imtixonlari"


class Kip(Base):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="kips")
    yoriqchi = models.ForeignKey(
        Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name="bergan_kips"
    )
    liniya = models.CharField(max_length=255)
    sana = models.DateField()
    muddat_oy = models.IntegerField(default=1)
    tugash = models.DateField()
    imzo_id = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "KIP"
        verbose_name_plural = "KIP yozuvlari"
        ordering = ["-sana"]


# ---------------------------------------------------------------------
# Bildirishnoma / xodisa / audit
# ---------------------------------------------------------------------

class Notification(Base):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="notifications")
    turi = models.CharField(max_length=32, default="info")
    sarlavha = models.CharField(max_length=255)
    matn = models.TextField(blank=True)
    sana = models.DateTimeField(default=timezone.now)
    oqilgan = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"
        ordering = ["-sana"]
        indexes = [models.Index(fields=["worker", "-sana"])]


class Incident(Base):
    """TB baxtsiz xodisasi yoki mashinist yoʻriqchisi avariyasi."""

    turi = models.CharField(
        max_length=16,
        choices=[("tb", "TB baxtsiz xodisa"), ("avariya", "Avariya")],
    )
    matn = models.TextField()
    author = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    sana = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Xodisa"
        verbose_name_plural = "Xodisalar"
        ordering = ["-sana"]


class AuditLog(Base):
    user = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    obyekt = models.CharField(max_length=255)
    amal = models.CharField(max_length=255)
    sana = models.DateTimeField(default=timezone.now)
    izoh = models.TextField(blank=True)

    class Meta:
        verbose_name = "Audit yozuvi"
        verbose_name_plural = "Audit jurnali"
        ordering = ["-sana"]
        indexes = [models.Index(fields=["-sana"])]

    def __str__(self) -> str:
        return f"{self.obyekt} — {self.amal}"


# ---------------------------------------------------------------------
# Ruxsat / koʻrinish override'lari
# ---------------------------------------------------------------------

class AccessOverride(Base):
    """
    Standart rol ruxsatlarini bekor qiluvchi sozlama.

    Ustuvorlik: user > position > role > standart (core/permissions.py).
    """

    SCOPE = [("role", "Rol"), ("position", "Lavozim"), ("user", "Foydalanuvchi")]

    scope = models.CharField(max_length=16, choices=SCOPE)
    scope_id = models.CharField(max_length=64, help_text="Rol kodi / lavozim id / ishchi id")
    key = models.CharField(max_length=64, help_text="Perm yoki FeatureKey")
    value = models.BooleanField()

    class Meta:
        verbose_name = "Ruxsat override"
        verbose_name_plural = "Ruxsat override'lari"
        unique_together = [("scope", "scope_id", "key")]

    def __str__(self) -> str:
        return f"{self.scope}:{self.scope_id} — {self.key} = {self.value}"


# ---------------------------------------------------------------------
# Refresh tokenlar — chiqishda bekor qilinadi
# ---------------------------------------------------------------------

class RefreshToken(Base):
    """
    Opaque refresh token. Bazada faqat SHA-256 hash saqlanadi —
    tokenning oʻzi hech qachon yozilmaydi.
    """

    worker = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Refresh token"
        verbose_name_plural = "Refresh tokenlar"
        ordering = ["-created_at"]

    @property
    def yaroqli(self) -> bool:
        return not self.revoked and self.expires_at > timezone.now()
