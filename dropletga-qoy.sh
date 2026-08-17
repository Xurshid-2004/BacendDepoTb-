#!/usr/bin/env bash
# =====================================================================
# TB backend — DigitalOcean Droplet'ga bir buyruq bilan oʻrnatish.
#
# Yangi Ubuntu 24.04 droplet ichida (root sifatida):
#
#   curl -fsSL https://raw.githubusercontent.com/Xurshid-2004/BacendDepoTb-/main/dropletga-qoy.sh | bash
#
# Skript bajaradigan ishlar:
#   1. Swap (2 GB) — 1 GB RAM'li droplet'da build oʻlib qolmasligi uchun
#   2. Docker
#   3. Firewall (22, 80, 443)
#   4. Kodni GitHub'dan klon qilish
#   5. .env.production — kalitlar avtomatik yaratiladi, domen IP'dan
#   6. Konteynerlarni koʻtarish
#
# Qayta ishga tushirish xavfsiz: mavjud swap, .env.production va baza
# saqlanadi, faqat yetishmagan qadam bajariladi.
# =====================================================================
set -e

DEPO="https://github.com/Xurshid-2004/BacendDepoTb-.git"
PAPKA="/root/BacendDepoTb-"

echo ""
echo "=============================================="
echo " TB backend oʻrnatilmoqda"
echo "=============================================="
echo ""

# --- 0. Tizimning boshlangʻich ishlari tugashini kutamiz ---------------
# Yangi droplet'da cloud-init apt'ni band qilib turadi — kutmasak
# Docker oʻrnatish «Could not get lock» xatosi bilan yiqiladi.
echo "[0/6] Tizim tayyorligi tekshirilmoqda..."
cloud-init status --wait >/dev/null 2>&1 || true

# --- 1. Swap ----------------------------------------------------------
echo "[1/6] Swap..."
if swapon --show 2>/dev/null | grep -q '/swapfile'; then
  echo "      allaqachon bor — oʻtkazib yuborildi"
else
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  grep -q 'vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
  sysctl -q vm.swappiness=10
  echo "      2 GB swap yoqildi"
fi

# --- 2. Docker --------------------------------------------------------
echo "[2/6] Docker..."
if command -v docker >/dev/null 2>&1; then
  echo "      allaqachon oʻrnatilgan"
else
  curl -fsSL https://get.docker.com | sh >/dev/null
  echo "      oʻrnatildi"
fi

# --- 3. Firewall ------------------------------------------------------
echo "[3/6] Firewall..."
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "      22, 80, 443 ochiq — qolgani yopiq"

# --- 4. Kod -----------------------------------------------------------
echo "[4/6] Kod GitHub'dan olinmoqda..."
if [ -d "$PAPKA/.git" ]; then
  cd "$PAPKA"
  git pull --ff-only
else
  git clone "$DEPO" "$PAPKA"
  cd "$PAPKA"
fi

# --- 5. Sozlamalar ----------------------------------------------------
echo "[5/6] Sozlamalar..."
if [ -f .env.production ]; then
  echo "      .env.production allaqachon bor — tegilmadi"
  DOMEN="$(grep -E '^TB_API_DOMAIN=' .env.production | cut -d= -f2-)"
else
  # Droplet oʻz IP'sini metadata xizmatidan biladi
  IP="$(curl -fsS --max-time 10 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)"
  [ -z "$IP" ] && IP="$(hostname -I | awk '{print $1}')"

  # sslip.io — IP'ni domenga aylantiradi, shunda Let's Encrypt
  # sertifikat bera oladi. Domen sotib olish shart emas.
  DOMEN="$IP.sslip.io"

  cat > .env.production <<EOF
# Avtomatik yaratildi: $(date +%F\ %H:%M)
TB_API_DOMAIN=$DOMEN

DJANGO_SECRET_KEY=$(openssl rand -hex 48)
JWT_SECRET=$(openssl rand -hex 48)

DJANGO_ALLOWED_HOSTS=$DOMEN,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://$DOMEN
CORS_ALLOWED_ORIGINS=https://fronted-depo-tb.vercel.app

POSTGRES_DB=tb
POSTGRES_USER=tb
POSTGRES_PASSWORD=$(openssl rand -hex 24)

NEXT_PUBLIC_DEPO_KOD=TCH-6
TB_ADMIN_TABEL=0212
TB_SEED=1
TB_XODIMLAR=1

WEB_CONCURRENCY=1
TZ=Asia/Tashkent
LOG_LEVEL=INFO
EOF
  chmod 600 .env.production
  echo "      kalitlar yaratildi, domen: $DOMEN"
fi

# --- 6. Ishga tushirish -----------------------------------------------
echo "[6/6] Konteynerlar koʻtarilmoqda (5-8 daqiqa)..."
echo ""
docker compose --env-file .env.production up -d --build

echo ""
echo "=============================================="
echo " TAYYOR"
echo ""
echo "   Manzilingiz:  https://$DOMEN"
echo "   Admin panel:  https://$DOMEN/admin/"
echo ""
echo " Sertifikat 1-2 daqiqada olinadi."
echo " Xodimlar roʻyxati fonda yozilmoqda (~3 daqiqa)."
echo ""
echo " Loglarni koʻrish:  cd $PAPKA && docker compose logs -f api"
echo "=============================================="
echo ""
