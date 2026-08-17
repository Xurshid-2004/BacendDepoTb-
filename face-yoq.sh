#!/usr/bin/env bash
# =====================================================================
# Yuz tanish (Face ID) xizmatini yoqish.
#
# Droplet 4 GB ga Resize qilingandan KEYIN ishga tushiriladi:
#
#   bash /root/BacendDepoTb-/face-yoq.sh
#
# Skript bajaradi:
#   1. Xotira yetarliligini tekshiradi (model RAM'da ~1.5 GB)
#   2. Kodni yangilaydi
#   3. .env.production ga FACE_* sozlamalarini yozadi (token avtomatik)
#   4. face konteynerini koʻtaradi va model yuklanishini kutadi
#
# Oʻchirish:
#   cd /root/BacendDepoTb-
#   sed -i 's|^FACE_SERVICE_URL=.*|FACE_SERVICE_URL=|' .env.production
#   docker compose --env-file .env.production stop face
#   docker compose --env-file .env.production up -d api
# =====================================================================
set -e

PAPKA="/root/BacendDepoTb-"
cd "$PAPKA"

echo ""
echo "=============================================="
echo " Face ID yoqilmoqda"
echo "=============================================="
echo ""

# --- 1. Xotira ---------------------------------------------------------
# Model RAM'da ~1.5 GB egallaydi. Postgres, Django va Caddy ham joy
# oladi. 4 GB dan kam boʻlsa OOM killer bazani oʻldiradi — shuning
# uchun bu yerda qatʼiy toʻxtatamiz.
RAM_MB="$(free -m | awk '/^Mem:/{print $2}')"
echo "[1/4] Xotira: ${RAM_MB} MB"
if [ "$RAM_MB" -lt 3400 ]; then
  echo ""
  echo "  TOʻXTATILDI — xotira yetarli emas."
  echo ""
  echo "  Yuz tanish modeli RAM'da ~1.5 GB egallaydi."
  echo "  Kerak: kamida 4 GB. Hozir: ${RAM_MB} MB."
  echo ""
  echo "  DigitalOcean panelida: Droplet → Resize → «CPU and RAM only»"
  echo "  → 4 GB tarifi → Resize. Soʻng shu skriptni qayta chaqiring."
  echo ""
  exit 1
fi

# --- 2. Kod ------------------------------------------------------------
echo "[2/4] Kod yangilanmoqda..."
git pull --ff-only

# --- 3. Sozlamalar -----------------------------------------------------
echo "[3/4] Sozlamalar..."
if grep -q '^FACE_SERVICE_URL=http' .env.production; then
  echo "      allaqachon yoqilgan — tegilmadi"
else
  # Eski (boʻsh) FACE_* qatorlarini olib tashlaymiz, keyin yangisini yozamiz
  sed -i '/^FACE_SERVICE_URL=/d; /^FACE_SERVICE_TOKEN=/d; /^FACE_THRESHOLD=/d; /^FACE_DET_SIZE=/d; /^FACE_MEM_LIMIT=/d' .env.production

  cat >> .env.production <<EOF

# --- Yuz tanish (face-yoq.sh yozgan) ---
FACE_SERVICE_URL=http://face:8000
FACE_SERVICE_TOKEN=$(openssl rand -hex 32)
FACE_THRESHOLD=0.62
FACE_DET_SIZE=640
FACE_MEM_LIMIT=2500m
EOF
  echo "      FACE_* yozildi, token yaratildi"
fi

# 4 GB da ikkita gunicorn worker bemalol sigʻadi
if grep -q '^WEB_CONCURRENCY=1$' .env.production; then
  sed -i 's/^WEB_CONCURRENCY=1$/WEB_CONCURRENCY=2/' .env.production
  echo "      WEB_CONCURRENCY 1 → 2"
fi

# --- 4. Ishga tushirish ------------------------------------------------
echo "[4/4] Konteynerlar koʻtarilmoqda..."
echo ""
docker compose --env-file .env.production --profile face up -d --build

echo ""
echo "Model yuklanmoqda (~281 MB) — birinchi safar 2-4 daqiqa oladi."
echo "Kutilmoqda..."

TAYYOR=0
for i in $(seq 1 60); do
  if docker compose --env-file .env.production exec -T face \
       curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    TAYYOR=1
    break
  fi
  sleep 10
done

echo ""
echo "=============================================="
if [ "$TAYYOR" = "1" ]; then
  echo " FACE ID YOQILDI"
  echo ""
  echo " Endi har bir xodim oʻz profilida Face ID qoʻshadi:"
  echo "   sayt → Ishchi sahifasi → Face ID qoʻshish"
  echo ""
  echo " Yuz qoʻshgandan keyin kirish oqimi:"
  echo "   tabel → Face ID → mos kelmasa → PIN"
else
  echo " OGOHLANTIRISH: xizmat 10 daqiqada javob bermadi."
  echo " Loglarni koʻring:"
  echo "   cd $PAPKA && docker compose logs -f face"
fi
echo "=============================================="
echo ""
