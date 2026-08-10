"""
=====================================================================
API marshrutlari — /api/v1/...

Frontend (lib/api.ts) va Flutter ilovasi shu manzillarga murojaat
qiladi. Har bir amal alohida endpoint — brauzerda hech qanday biznes
qaror qabul qilinmaydi.
=====================================================================
"""

from django.urls import path

from api import views_auth as auth
from api import views_ops as ops
from api import views_state as st

urlpatterns = [
    # --- holat / xizmat ---
    path("health", st.health, name="health"),
    path("bootstrap", st.bootstrap, name="bootstrap"),
    path("state", st.state, name="state"),
    path("verify/<uuid:sig_id>", st.verify, name="verify"),

    # --- autentifikatsiya ---
    path("auth/check", auth.check, name="auth-check"),
    path("auth/login", auth.login, name="login"),
    path("auth/face-login", auth.face_login, name="face-login"),
    path("auth/register", auth.register, name="register"),
    path("auth/set-pin", auth.set_pin, name="set-pin"),
    path("auth/refresh", auth.refresh, name="refresh"),
    path("auth/logout", auth.logout, name="logout"),
    path("me", auth.me, name="me"),
    path("me/face", auth.me_face, name="me-face"),
    path("admin/reset-pin", auth.reset_pin, name="reset-pin"),

    # --- arizalar ---
    path("requests", ops.request_create, name="request-create"),
    path("requests/<uuid:req_id>", ops.request_update, name="request-update"),
    path("requests/<uuid:req_id>/advance", ops.request_advance, name="request-advance"),
    path("requests/<uuid:req_id>/reject", ops.request_reject, name="request-reject"),

    # --- TB jurnali ---
    path("journal", ops.journal_add, name="journal-add"),
    path("journal/<uuid:entry_id>/sign", ops.journal_sign, name="journal-sign"),

    # --- omborxona ---
    path("stock/in", ops.stock_in, name="stock-in"),

    # --- talon / imtixon / KIP ---
    path("talons/toggle", ops.talon_toggle, name="talon-toggle"),
    path("kips", ops.kip_add, name="kip-add"),
    path("exams", ops.exam_set, name="exam-set"),

    # --- buyum / norma ---
    path("items", ops.item_upsert, name="item-upsert"),
    path("norms", ops.norm_upsert, name="norm-upsert"),
    path("norms/<uuid:norm_id>", ops.norm_delete, name="norm-delete"),

    # --- ishchilar ---
    path("workers", ops.worker_upsert, name="worker-upsert"),
    path("workers/import", ops.worker_import, name="worker-import"),
    path("workers/<uuid:worker_id>", ops.worker_delete, name="worker-delete"),
    path("workers/<uuid:worker_id>/pin", ops.worker_pin, name="worker-pin"),
    path("workers/<uuid:worker_id>/face", auth.worker_face, name="worker-face"),
    path("workers/<uuid:worker_id>/face-reset", ops.worker_face_reset, name="worker-face-reset"),

    # --- lavozim / birlik / liniya ---
    path("positions", ops.position_add, name="position-add"),
    path("positions/<uuid:position_id>", ops.position_update, name="position-update"),
    path("units", ops.unit_manage, name="unit-manage"),
    path("lines", ops.line_manage, name="line-manage"),

    # --- ruxsatlar ---
    path("access", ops.access_set, name="access-set"),

    # --- xodisalar / bildirishnomalar ---
    path("incidents", ops.incident_add, name="incident-add"),
    path("notifications/read", ops.notification_read, name="notification-read"),
]
