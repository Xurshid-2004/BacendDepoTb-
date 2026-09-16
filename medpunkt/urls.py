"""
=====================================================================
Med-punkt marshrutlari — `/api/v1/medpunkt/...`

Ikki xil mijoz, ikki xil tekshiruv:

  kiosk (X-API-Key)      ingest · hodisa · sync
  web panel (JWT)        olchovlar · hodisalar · meyorlar · sozlamalar

Caddy sozlamasi oʻzgarmaydi — `/api/*` allaqachon Django'ga boradi.
=====================================================================
"""

from django.urls import path

from medpunkt import views_kiosk as kiosk
from medpunkt import views_panel as panel

urlpatterns = [
    # --- kiosk (X-API-Key) ---
    path("ingest", kiosk.ingest, name="medpunkt-ingest"),
    path("hodisa", kiosk.hodisa, name="medpunkt-hodisa"),
    path("sync", kiosk.sync, name="medpunkt-sync"),

    # --- panel (JWT + «Ruxsatlar va koʻrinishlar») ---
    path("olchovlar", panel.olchovlar, name="medpunkt-olchovlar"),
    path("hodisalar", panel.hodisalar, name="medpunkt-hodisalar"),
    path("hodisalar/<uuid:hodisa_id>/korildi", panel.hodisa_korildi, name="medpunkt-hodisa-korildi"),
    path("meyorlar", panel.meyorlar, name="medpunkt-meyorlar"),
    path("meyorlar/<uuid:worker_id>", panel.meyor_ochir, name="medpunkt-meyor-ochir"),
    path("sozlamalar", panel.sozlamalar, name="medpunkt-sozlamalar"),
]
