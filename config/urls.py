"""
=====================================================================
Asosiy marshrutlar.

  /admin/    — Django admin paneli (33 jadval uchun tayyor CRUD)
  /api/v1/   — ilova API'si
  /api/      — eski Next.js manzillari bilan moslik (Flutter ilovasi
               hozircha /api/auth/login kabi manzillarga murojaat qiladi)
=====================================================================
"""

from django.contrib import admin
from django.urls import include, path

from api import views_state

admin.site.site_header = "TB tizimi — boshqaruv"
admin.site.site_title = "TB tizimi"
admin.site.index_title = "Maʼlumotlar boshqaruvi"

urlpatterns = [
    path("admin/", admin.site.urls),

    # Asosiy API
    path("api/v1/", include("api.urls")),

    # Eski manzillar bilan moslik — Flutter ilovasi yangilanmaguncha
    # (app_flutter/lib/core/api.dart /api/auth/login ga murojaat qiladi)
    path("api/", include("api.urls")),

    # Ildizda sogʻliq tekshiruvi
    path("health", views_state.health),
]
