"""
=====================================================================
Med-punkt — admin paneli (/admin/).

Oʻlchov va hodisa yozuvlari kioskdan keladi, shuning uchun bu yerda
ular FAQAT OʻQISH uchun: admin qoʻli bilan tibbiy natijani
oʻzgartirib boʻlmasin. Tahrir qilinadigani — chegaralar va shaxsiy
meʼyorlar.
=====================================================================
"""

from __future__ import annotations

from django.contrib import admin

from medpunkt.models import Hodisa, IshchiMeyor, MedPunkt, Olchov, Sozlama


@admin.register(MedPunkt)
class MedPunktAdmin(admin.ModelAdmin):
    list_display = ("kod", "nom", "faol", "oxirgi_aloqa", "olchovlar_soni")
    list_filter = ("faol",)
    search_fields = ("kod", "nom")

    @admin.display(description="Oʻlchovlar")
    def olchovlar_soni(self, obj):
        return obj.olchovlar.count()


@admin.register(Sozlama)
class SozlamaAdmin(admin.ModelAdmin):
    list_display = (
        "__str__", "alko_chegara_mg_l", "alko_chegara_passiv_mg_l",
        "qon_sis_max", "qon_dia_max", "qon_puls_min", "qon_puls_max", "yangilandi",
    )
    readonly_fields = ("yangilandi",)

    def has_add_permission(self, request):
        # Chegaralar yagona yozuv — ikkinchisi ochilmasin.
        return not Sozlama.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IshchiMeyor)
class IshchiMeyorAdmin(admin.ModelAdmin):
    list_display = (
        "worker", "sis_max", "dia_max", "puls_min", "puls_max",
        "shifokor", "yangilandi", "deleted",
    )
    list_filter = ("deleted",)
    search_fields = ("worker__tabel", "worker__familiya", "worker__ism")
    autocomplete_fields = ("worker",)
    readonly_fields = ("yangilandi",)


@admin.register(Olchov)
class OlchovAdmin(admin.ModelAdmin):
    list_display = (
        "olchov_vaqti", "tur", "worker", "tabel", "holat",
        "med_punkt", "qurilma", "arxivlangan",
    )
    list_filter = ("tur", "holat", "med_punkt", "arxivlangan", "egasiz")
    search_fields = ("tabel", "worker__tabel", "worker__familiya", "unik_kalit")
    date_hierarchy = "olchov_vaqti"
    readonly_fields = tuple(
        f.name for f in Olchov._meta.fields if f.name not in ("arxivlangan", "deleted")
    )

    def has_add_permission(self, request):
        # Oʻlchov faqat kioskdan keladi — qoʻlda kiritilmaydi.
        return False


@admin.register(Hodisa)
class HodisaAdmin(admin.ModelAdmin):
    list_display = ("vaqt", "tur", "worker", "tabel", "med_punkt", "korildi")
    list_filter = ("tur", "korildi", "med_punkt")
    search_fields = ("tabel", "worker__tabel", "sessiya_id", "tafsilot")
    date_hierarchy = "vaqt"
    readonly_fields = tuple(
        f.name for f in Hodisa._meta.fields if f.name not in ("korildi", "deleted")
    )

    def has_add_permission(self, request):
        return False
