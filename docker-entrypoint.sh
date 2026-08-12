#!/bin/sh
# =====================================================================
# Konteyner ishga tushganda:
#   1. Baza tayyor boʻlishini kutadi
#   2. Migratsiyalarni bajaradi
#   3. Statik fayllarni yigʻadi (admin paneli uchun)
#   4. Boshlangʻich normativ maʼlumotni yozadi (bir marta)
#   5. gunicorn'ni ishga tushiradi
#
# Har bir qadam xato bersa konteyner toʻxtaydi — server "yarim ishlagan"
# holatda qolmaydi.
# =====================================================================
set -e

# ---------------------------------------------------------------------
# Serverni ishga tushirish — buyruq ichida kengaymagan oʻzgaruvchi
# qolgan boʻlsa (masalan panel bergan "$PORT"), shell orqali qayta
# oʻtkazamiz. Ikki joydan chaqirilgani uchun funksiyaga chiqarildi.
# ---------------------------------------------------------------------
ishga_tushir() {
  case "$*" in
    *'$'*)
      echo "[tb] Buyruqda kengaymagan oʻzgaruvchi bor — shell orqali qayta ishga tushiriladi"
      exec /bin/sh -c "exec $*"
      ;;
  esac
  exec "$@"
}

# ---------------------------------------------------------------------
# Takroriy chaqiruvdan himoya.
#
# railway.json dagi startCommand `tb-entrypoint gunicorn ...` deb
# yozilgan — shu bilan panelning "Custom Start Command" sozlamasi
# bekor qilinadi va entrypoint chetlab oʻtilmaydi. Platforma
# Dockerfile ENTRYPOINT'ini ham saqlab qolsa, skript ikki marta
# chaqiriladi. Migratsiya va collectstatic'ni takrorlash shart emas:
# birinchi chaqiruv hammasini bajaradi, ikkinchisi toʻgʻridan-toʻgʻri
# gunicorn'ga oʻtadi.
# ---------------------------------------------------------------------
if [ "${TB_ENTRYPOINT_BAJARILDI:-}" = "1" ]; then
  echo "[tb] Tayyorlash allaqachon bajarilgan — server ishga tushiriladi"
  ishga_tushir "$@"
fi
export TB_ENTRYPOINT_BAJARILDI=1

echo "[tb] Baza ulanishini kutmoqda..."
python - <<'PY'
import os, sys, time
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.db import connection

for urinish in range(1, 61):
    try:
        connection.ensure_connection()
        print(f"[tb] Baza tayyor ({urinish}-urinish)")
        sys.exit(0)
    except Exception as e:
        if urinish == 1:
            print(f"[tb] Kutilmoqda: {e}")
        time.sleep(2)

print("[tb] XATO: bazaga 120 soniyada ulanib boʻlmadi")
sys.exit(1)
PY

echo "[tb] Migratsiyalar..."
python manage.py migrate --noinput

echo "[tb] Statik fayllar..."
python manage.py collectstatic --noinput --clear >/dev/null

# --- Maʼlumot yozish — FONDA -----------------------------------------
#
# Bu qadamlar (normativ maʼlumot, 296 xodim va ularning suratlari)
# uzoq bazaga yuzlab soʻrov yuboradi va bir necha daqiqa olishi mumkin.
# Ilgari ular gunicorn'dan OLDIN bajarilardi — natijada platformaning
# healthcheck'i (5 daqiqa) server koʻtarilishini kutolmay deploy'ni
# muvaffaqiyatsiz deb belgilardi.
#
# Endi server darrov koʻtariladi, maʼlumot esa orqa fonda yoziladi.
# Buyruqlar takror ishga tushishga chidamli, shuning uchun yarim
# yoʻlda uzilib qolsa keyingi deploy davom ettiradi.
(
  if [ "${TB_SEED:-1}" = "1" ]; then
    echo "[tb] Boshlangʻich maʼlumot tekshirilmoqda..."
    python manage.py seed || echo "[tb] OGOHLANTIRISH: seed bajarilmadi"
  fi

  if [ "${TB_XODIMLAR:-1}" = "1" ]; then
    echo "[tb] Kadrlar roʻyxati yuklanmoqda..."
    python manage.py import_xodimlar || echo "[tb] OGOHLANTIRISH: kadrlar yuklanmadi"
  fi

  # Administrator tabel raqami. Panelda TB_ADMIN_TABEL berilmagan boʻlsa
  # shu depo uchun kelishilgan qiymat ishlatiladi.
  #
  # PIN bu yerda ATAYLAB berilmaydi: hisob PIN'siz yaratiladi va
  # administrator birinchi kirishda oʻziga PIN oʻrnatadi. Shunda parol
  # na kodda, na muhit oʻzgaruvchisida saqlanmaydi — repo ochiq boʻlgani
  # uchun bu muhim. admin_yarat mavjud hisobning PIN'iga tegmaydi.
  TB_ADMIN_TABEL="${TB_ADMIN_TABEL:-0212}"
  export TB_ADMIN_TABEL

  if [ -n "${TB_ADMIN_TABEL:-}" ]; then
    echo "[tb] Administrator hisobi tekshirilmoqda ($TB_ADMIN_TABEL)..."
    python manage.py admin_yarat || echo "[tb] OGOHLANTIRISH: admin yaratilmadi"
  fi

  echo "[tb] Fon vazifalari tugadi."
) &

echo "[tb] Ishga tushmoqda..."

# Railway/Fly panelidagi "Custom Start Command" konteynerga exec shaklida
# uzatiladi — oradа shell boʻlmaydi va $PORT kabi oʻzgaruvchilar kengaymaydi.
# Natijada gunicorn portni "$PORT" degan matn deb qabul qiladi va
# "'$PORT' is not a valid port number" xatosi bilan toʻxtaydi; hech qanday
# port band boʻlmagani uchun platformaning healthcheck'i yiqiladi.
ishga_tushir "$@"
