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

# Normativ maʼlumot faqat bazа boʻsh boʻlganda yoziladi
if [ "${TB_SEED:-1}" = "1" ]; then
  echo "[tb] Boshlangʻich maʼlumot tekshirilmoqda..."
  python manage.py seed
fi

# Kadrlar roʻyxati (296 xodim: tabel, F.I.Sh., lavozim, surat).
# Buyruq takror ishga tushishga chidamli: mavjud tabel yangilanadi,
# PIN va rollarga tegilmaydi. TB_XODIMLAR=0 boʻlsa oʻtkazib yuboriladi.
if [ "${TB_XODIMLAR:-1}" = "1" ]; then
  echo "[tb] Kadrlar roʻyxati yuklanmoqda..."
  python manage.py import_xodimlar
fi

# Administrator hisobi — TB_ADMIN_TABEL berilgan boʻlsa.
# Buyruq bir marta ishlaydi: hisob bor boʻlsa PIN'ga tegmaydi.
if [ -n "${TB_ADMIN_TABEL:-}" ]; then
  echo "[tb] Administrator hisobi tekshirilmoqda..."
  python manage.py admin_yarat
fi

echo "[tb] Ishga tushmoqda..."

# Railway/Fly panelidagi "Custom Start Command" konteynerga exec shaklida
# uzatiladi — oradа shell boʻlmaydi va $PORT kabi oʻzgaruvchilar kengaymaydi.
# Natijada gunicorn portni "$PORT" degan matn deb qabul qiladi va
# "'$PORT' is not a valid port number" xatosi bilan toʻxtaydi; hech qanday
# port band boʻlmagani uchun platformaning healthcheck'i yiqiladi.
#
# Buyruqda kengaymagan oʻzgaruvchi qolgan boʻlsa, uni shell orqali qayta
# oʻtkazamiz — shunda $PORT oʻz qiymatini oladi.
case "$*" in
  *'$'*)
    echo "[tb] Buyruqda kengaymagan oʻzgaruvchi bor — shell orqali qayta ishga tushiriladi"
    exec /bin/sh -c "exec $*"
    ;;
esac

exec "$@"
