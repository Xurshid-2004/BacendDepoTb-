"""
=====================================================================
Django admin paneli — /admin/

Bu Django'ning eng kuchli tomoni: barcha jadvallar uchun tayyor
qidiruv/filtr/tahrir interfeysi. Ilovaning oʻzida yozilmagan har qanday
tuzatishni shu yerdan qilish mumkin.

DIQQAT: PIN hash maydoni ataylab faqat oʻqish uchun koʻrsatiladi —
uni qoʻlda tahrirlash mumkin emas, faqat "PIN tiklash" amali orqali.
=====================================================================
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from core.models import (
    AccessOverride, AuditLog, Card, CardIssue, CardReturn, Depo, Exam,
    Incident, Item, JournalEntry, Kip, Line, Norm, Notification, Position,
    RefreshToken, Request, RequestLine, Signature, Stock, StockMove,
    Talon, TalonHistory, Unit, Worker,
)


# ---------------------------------------------------------------------
# Depo va maʼlumotnomalar
# ---------------------------------------------------------------------

@admin.register(Depo)
class DepoAdmin(admin.ModelAdmin):
    list_display = ("kod", "nomi", "tashkilot", "qish_boshi", "qish_oxiri", "seq")
    search_fields = ("kod", "nomi")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("tartib", "nomi", "arxiv", "ishchilar_soni")
    list_filter = ("arxiv",)
    search_fields = ("nomi",)
    ordering = ("tartib",)

    @admin.display(description="Ishchilar")
    def ishchilar_soni(self, obj):
        return obj.workers.count()


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("nomi", "kod", "unit", "qishki", "narx", "qoldiq", "arxiv")
    list_filter = ("qishki", "arxiv", "unit")
    search_fields = ("nomi", "kod")

    @admin.display(description="Ombor qoldigʻi")
    def qoldiq(self, obj):
        s = getattr(obj, "stock", None)
        return s.qoldiq if s else 0


@admin.register(Norm)
class NormAdmin(admin.ModelAdmin):
    list_display = ("position", "item", "muddat_kor", "qishki")
    list_filter = ("qishki", "position")
    search_fields = ("position__nomi", "item__nomi")
    autocomplete_fields = ("position", "item")

    @admin.display(description="Muddat")
    def muddat_kor(self, obj):
        return "Ish. Chiqqun" if obj.muddat_oy is None else f"{obj.muddat_oy} oy"


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("nomi", "tartib")
    ordering = ("tartib",)


@admin.register(Line)
class LineAdmin(admin.ModelAdmin):
    list_display = ("nomi", "tartib")
    ordering = ("tartib",)


# ---------------------------------------------------------------------
# Ishchilar
# ---------------------------------------------------------------------

@admin.register(Worker)
class WorkerAdmin(BaseUserAdmin):
    ordering = ("familiya", "ism")
    list_display = ("tabel", "fio_kor", "position", "rollar", "pin_holati", "faol")
    list_filter = ("faol", "deleted", "is_staff", "position", "jinsi")
    search_fields = ("tabel", "familiya", "ism", "otasi", "telefon")
    filter_horizontal = ("positions", "groups", "user_permissions")
    readonly_fields = ("pin_hash", "last_login", "created_at")
    actions = ("pin_tiklash", "faolsizlantirish", "faollashtirish")

    fieldsets = (
        ("Shaxs", {
            "fields": ("tabel", "familiya", "ism", "otasi", "jinsi", "telefon", "kirgan_sana")
        }),
        ("Lavozim va joy", {
            "fields": ("depo", "position", "positions", "sex", "ish_joyi", "kolonna", "yoriqchi")
        }),
        ("Oʻlchamlar", {
            "fields": ("boyi", "kiyim_olchami", "poyabzal_olchami", "bosh_kiyim_olchami"),
            "classes": ("collapse",),
        }),
        ("Kirish", {
            "fields": ("roles", "pin_hash", "pin_reset", "password"),
            "description": "PIN'ni qoʻlda tahrirlab boʻlmaydi — «PIN tiklash» amalidan foydalaning.",
        }),
        ("Holat", {"fields": ("faol", "deleted", "is_staff", "is_superuser")}),
        ("Xizmat", {"fields": ("last_login", "created_at"), "classes": ("collapse",)}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("tabel", "familiya", "ism", "otasi", "depo", "position", "roles"),
        }),
    )

    @admin.display(description="F.I.O.")
    def fio_kor(self, obj):
        return obj.fio

    @admin.display(description="Rollar")
    def rollar(self, obj):
        return ", ".join(obj.roles or []) or "—"

    @admin.display(description="PIN")
    def pin_holati(self, obj):
        if obj.pin_reset:
            return format_html('<span style="color:#f59e0b">tiklanishi kerak</span>')
        if obj.pin_hash:
            return format_html('<span style="color:#22c55e">oʻrnatilgan</span>')
        return format_html('<span style="color:#94a3b8">yoʻq</span>')

    @admin.action(description="PIN'ni tiklash (ishchi oʻzi yangisini qoʻyadi)")
    def pin_tiklash(self, request, queryset):
        from core.tokens import revoke_all

        n = 0
        for w in queryset:
            w.clear_pin()
            w.save(update_fields=["pin_hash", "pin_reset"])
            revoke_all(w)
            n += 1
        self.message_user(request, f"{n} ta ishchining PIN'i tiklandi", messages.SUCCESS)

    @admin.action(description="Faolsizlantirish")
    def faolsizlantirish(self, request, queryset):
        n = queryset.update(faol=False)
        self.message_user(request, f"{n} ta ishchi faolsizlantirildi", messages.SUCCESS)

    @admin.action(description="Faollashtirish")
    def faollashtirish(self, request, queryset):
        n = queryset.update(faol=True)
        self.message_user(request, f"{n} ta ishchi faollashtirildi", messages.SUCCESS)


# ---------------------------------------------------------------------
# Kartochka
# ---------------------------------------------------------------------

class CardIssueInline(admin.TabularInline):
    model = CardIssue
    extra = 0
    autocomplete_fields = ("item",)


class CardReturnInline(admin.TabularInline):
    model = CardReturn
    extra = 0
    autocomplete_fields = ("item",)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("worker", "ochilgan", "berilgan_soni")
    search_fields = ("worker__tabel", "worker__familiya")
    autocomplete_fields = ("worker",)
    inlines = (CardIssueInline, CardReturnInline)

    @admin.display(description="Berilgan buyumlar")
    def berilgan_soni(self, obj):
        return obj.berilgan.count()


# ---------------------------------------------------------------------
# Arizalar
# ---------------------------------------------------------------------

class RequestLineInline(admin.TabularInline):
    model = RequestLine
    extra = 0
    autocomplete_fields = ("item",)


class TransitionInline(admin.TabularInline):
    model = __import__("core.models", fromlist=["Transition"]).Transition
    extra = 0
    readonly_fields = ("from_status", "to_status", "user", "sana", "izoh")
    can_delete = False


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ("raqam", "worker", "turi", "status", "yaratilgan", "yakunlangan")
    list_filter = ("status", "turi", "yaratilgan")
    search_fields = ("raqam", "worker__tabel", "worker__familiya")
    autocomplete_fields = ("worker", "yaratgan")
    date_hierarchy = "yaratilgan"
    inlines = (RequestLineInline, TransitionInline)


@admin.register(Signature)
class SignatureAdmin(admin.ModelAdmin):
    list_display = ("doc_type", "doc_id", "field", "user", "sana", "bekor")
    list_filter = ("doc_type", "bekor")
    search_fields = ("doc_id", "hash")
    readonly_fields = ("hash",)


# ---------------------------------------------------------------------
# Jurnal / ombor
# ---------------------------------------------------------------------

@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("sana", "bosqich", "nomuvofiqlik_qisqa", "masul", "muddat", "bajarildi")
    list_filter = ("bosqich", "bajarildi")
    search_fields = ("nomuvofiqlik", "chora", "masul")
    date_hierarchy = "sana"

    @admin.display(description="Nomuvofiqlik")
    def nomuvofiqlik_qisqa(self, obj):
        return (obj.nomuvofiqlik or "")[:60]


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("item", "qoldiq")
    search_fields = ("item__nomi",)
    autocomplete_fields = ("item",)


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ("sana", "item", "turi", "soni", "izoh")
    list_filter = ("turi", "sana")
    search_fields = ("item__nomi", "izoh")
    date_hierarchy = "sana"
    autocomplete_fields = ("item",)


# ---------------------------------------------------------------------
# Talon / imtixon / KIP
# ---------------------------------------------------------------------

class TalonHistoryInline(admin.TabularInline):
    model = TalonHistory
    extra = 0
    readonly_fields = ("amal", "sana", "tb_xodim", "sabab")


@admin.register(Talon)
class TalonAdmin(admin.ModelAdmin):
    list_display = ("worker", "raqam", "olingan")
    list_filter = ("raqam", "olingan")
    search_fields = ("worker__tabel", "worker__familiya")
    autocomplete_fields = ("worker",)
    inlines = (TalonHistoryInline,)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("worker", "oxirgi", "davriylik_oy", "natija")
    list_filter = ("natija",)
    search_fields = ("worker__tabel", "worker__familiya")
    autocomplete_fields = ("worker",)


@admin.register(Kip)
class KipAdmin(admin.ModelAdmin):
    list_display = ("sana", "worker", "yoriqchi", "liniya", "muddat_oy", "tugash")
    list_filter = ("liniya", "sana")
    search_fields = ("worker__tabel", "worker__familiya", "liniya")
    autocomplete_fields = ("worker", "yoriqchi")
    date_hierarchy = "sana"


# ---------------------------------------------------------------------
# Bildirishnoma / xodisa / audit / ruxsat
# ---------------------------------------------------------------------

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("sana", "worker", "sarlavha", "turi", "oqilgan")
    list_filter = ("turi", "oqilgan")
    search_fields = ("sarlavha", "matn", "worker__tabel")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("sana", "turi", "matn_qisqa", "author")
    list_filter = ("turi",)
    search_fields = ("matn",)
    date_hierarchy = "sana"

    @admin.display(description="Matn")
    def matn_qisqa(self, obj):
        return (obj.matn or "")[:80]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("sana", "user", "obyekt", "amal", "izoh")
    list_filter = ("amal",)
    search_fields = ("obyekt", "amal", "izoh", "user__tabel")
    date_hierarchy = "sana"
    readonly_fields = ("user", "obyekt", "amal", "sana", "izoh")

    def has_add_permission(self, request):
        return False        # audit qoʻlda yozilmaydi


@admin.register(AccessOverride)
class AccessOverrideAdmin(admin.ModelAdmin):
    list_display = ("scope", "scope_id", "key", "value")
    list_filter = ("scope", "value")
    search_fields = ("scope_id", "key")


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("worker", "created_at", "expires_at", "revoked", "user_agent")
    list_filter = ("revoked",)
    search_fields = ("worker__tabel",)
    readonly_fields = ("token_hash",)

    def has_add_permission(self, request):
        return False
