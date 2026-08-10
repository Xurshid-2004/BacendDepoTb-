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

echo "[tb] Build tayyor."
