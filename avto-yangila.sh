#!/usr/bin/env bash
# =====================================================================
# TB backend — GitHub'ga push qilinganda serverni OʻZI yangilaydi.
#
# Vercel frontendni push'dan keyin darrov qayta yigʻadi; DigitalOcean
# Droplet'da bunday narsa yoʻq — kimdir kirib `git pull` qilishi kerak.
# Bu skript shu ishni avtomatlashtiradi: har 2 daqiqada GitHub'ni
# tekshiradi, yangi commit boʻlsa tortib olib konteynerni qayta yigʻadi.
#
# Bir marta oʻrnatish (Droplet konsolida, root sifatida):
#
#     cd /root/BacendDepoTb- && git pull && bash avto-yangila.sh ornat
#
# `ornat` uch ishni bajaradi:
#     1. kodni GitHub'dagi oxirgi holatga keltiradi
#     2. konteynerni SHU ZAHOTI qayta yigʻadi
#     3. systemd taymerini yoqadi — keyingi push'lar avtomatik yetadi
#
# Boshqarish:
#     systemctl status  tb-yangila.timer     — ishlayaptimi
#     systemctl stop    tb-yangila.timer     — vaqtincha toʻxtatish
#     systemctl start   tb-yangila.timer     — qayta yoqish
#     journalctl -u tb-yangila.service -n 50 — soʻnggi loglar
#     bash avto-yangila.sh                   — hoziroq tekshirish (oʻzgargan boʻlsa yigʻadi)
#     bash avto-yangila.sh majbur            — oʻzgarmagan boʻlsa ham qayta yigʻish
# =====================================================================
set -euo pipefail

PAPKA="${TB_PAPKA:-/root/BacendDepoTb-}"
BRANCH="${TB_BRANCH:-main}"
ORALIQ="${TB_ORALIQ:-2min}"          # tekshirish oraligʻi (systemd formati)
AMAL="${1:-}"

# ---------------------------------------------------------------------
# Konteynerni qayta yigʻish
# ---------------------------------------------------------------------
qayta_yig() {
  # .env.production serverda yaratiladi va repoda yoʻq — mavjud boʻlsa
  # ishlatamiz, boʻlmasa docker compose oʻz standartlari bilan koʻtaradi.
  if [ -f .env.production ]; then
    docker compose --env-file .env.production up -d --build
  else
    docker compose up -d --build
  fi

  # Eski image'lar diskni toʻldirmasin. Volume'larga tegilmaydi — baza xavfsiz.
  docker image prune -f >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------
# GitHub'ni tekshirish; oʻzgargan boʻlsa (yoki majbur boʻlsa) yigʻish
# ---------------------------------------------------------------------
yangila() {
  local majbur="${1:-}"

  git fetch --quiet origin "$BRANCH"
  local joriy yangi
  joriy="$(git rev-parse HEAD)"
  yangi="$(git rev-parse "origin/$BRANCH")"

  if [ "$joriy" = "$yangi" ] && [ "$majbur" != "majbur" ]; then
    echo "[tb] Yangilik yoʻq (${joriy:0:7})"
    return 0
  fi

  if [ "$joriy" != "$yangi" ]; then
    echo "[tb] Yangi commit: ${joriy:0:7} → ${yangi:0:7}"
  else
    echo "[tb] Majburiy qayta yigʻish (${joriy:0:7})"
  fi

  git reset --hard "origin/$BRANCH"
  qayta_yig
  echo "[tb] Tayyor: $(git log -1 --pretty='%h %s')"
}

# ---------------------------------------------------------------------
# Oʻrnatish rejimi — systemd service + timer yaratadi
# ---------------------------------------------------------------------
if [ "$AMAL" = "ornat" ]; then
  if [ "$(id -u)" != "0" ]; then
    echo "[tb] XATO: bu buyruq root sifatida bajarilishi kerak (sudo)" >&2
    exit 1
  fi

  echo "[tb] Avto-yangilanish oʻrnatilmoqda: $PAPKA ($BRANCH), har $ORALIQ"
  cd "$PAPKA"

  cat > /etc/systemd/system/tb-yangila.service <<EOF
[Unit]
Description=TB backend — GitHub'dan yangilanish
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PAPKA
Environment=TB_PAPKA=$PAPKA
Environment=TB_BRANCH=$BRANCH
ExecStart=/bin/bash $PAPKA/avto-yangila.sh
EOF

  cat > /etc/systemd/system/tb-yangila.timer <<EOF
[Unit]
Description=TB backend yangilanishini muntazam tekshirish

[Timer]
OnBootSec=3min
OnUnitActiveSec=$ORALIQ
AccuracySec=15s
Unit=tb-yangila.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable --now tb-yangila.timer

  # Birinchi yigʻish — kutib turmasdan, hoziroq. Shunda serverdagi kod
  # ham, ishlayotgan konteyner ham repo bilan bir xil boʻladi.
  echo "[tb] Birinchi yigʻish boshlandi (bir necha daqiqa olishi mumkin)..."
  yangila majbur

  echo ""
  echo "[tb] Oʻrnatildi. Endi har push ~$ORALIQ ichida oʻzi yetib keladi."
  systemctl status tb-yangila.timer --no-pager | head -4
  exit 0
fi

# ---------------------------------------------------------------------
# Oddiy rejim (taymer shuni chaqiradi) yoki qoʻlda «majbur»
# ---------------------------------------------------------------------
cd "$PAPKA"
yangila "$AMAL"
