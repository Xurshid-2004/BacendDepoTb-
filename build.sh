#!/usr/bin/env bash
# =====================================================================
# Render — build bosqichi (har deploy'da bir marta bajariladi).
#
#   1. Bogʻliqliklar
#   2. Statik fayllar (Django admin paneli uchun — WhiteNoise beradi)
#   3. Migratsiyalar
#   4. Boshlangʻich normativ maʼlumot (faqat bazа boʻsh boʻlsa)
#
# Har qadam xato bersa deploy TOʻXTAYDI — yarim koʻchgan baza bilan
# ishlab turgan servis qolib ketmasin.
# =====================================================================
set -o errexit
set -o nounset
set -o pipefail

echo "[tb] Bogʻliqliklar oʻrnatilmoqda..."
pip install --no-cache-dir -r requirements.txt

echo "[tb] Statik fayllar yigʻilmoqda..."
python manage.py collectstatic --noinput

echo "[tb] Migratsiyalar bajarilmoqda..."
python manage.py migrate --noinput

# Seed idempotent: mavjud maʼlumotni takrorlamaydi.
# Oʻchirish uchun Render'da TB_SEED=0 qoʻying.
if [ "${TB_SEED:-1}" = "1" ]; then
  echo "[tb] Boshlangʻich maʼlumot tekshirilmoqda..."
  python manage.py seed
fi

# Kadrlar roʻyxati (296 xodim, surati bilan). Takrorlanmaydi: mavjud
# tabel yangilanadi, PIN va rollarga tegilmaydi. TB_XODIMLAR=0 — oʻchiradi.
if [ "${TB_XODIMLAR:-1}" = "1" ]; then
  echo "[tb] Kadrlar roʻyxati yuklanmoqda..."
  python manage.py import_xodimlar
fi

# Administrator hisobi — TB_ADMIN_TABEL berilgan boʻlsa.
# Hisob bor boʻlsa PIN'ga tegilmaydi (deploy PIN'ni qaytarib qoʻymaydi).
if [ -n "${TB_ADMIN_TABEL:-}" ]; then
  echo "[tb] Administrator hisobi tekshirilmoqda..."
  python manage.py admin_yarat
fi

echo "[tb] Build tayyor."
