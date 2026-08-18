#!/usr/bin/env bash
# =====================================================================
# TB backend — GitHub'ga push qilinganda serverni OʻZI yangilaydi.
#
# Vercel frontendni push'dan keyin darrov qayta yigʻadi; DigitalOcean
# Droplet'da bunday narsa yoʻq — kimdir kirib `git pull` qilishi kerak.
# Bu skript shu ishni avtomatlashtiradi: har 2 daqiqada GitHub'ni
# tekshiradi, yangi commit boʻlsa tortib olib konteynerni qayta yigʻadi.
#
# Bir marta oʻrnatish (serverda, root sifatida):
#
#     cd /root/BacendDepoTb-
#     git pull
#     bash avto-yangila.sh ornat
#
# Shundan keyin hech narsa qilish shart emas: push qilingandan ~2 daqiqa
# ichida server yangilanadi va docker-entrypoint migratsiya, kadrlar
# roʻyxati va admin hisobini oʻzi bajaradi.
#
# Boshqarish:
#     systemctl status  tb-yangila.timer     — ishlayaptimi
#     systemctl stop    tb-yangila.timer     — vaqtincha toʻxtatish
#     systemctl start   tb-yangila.timer     — qayta yoqish
#     journalctl -u tb-yangila.service -n 50 — soʻnggi loglar
#     bash avto-yangila.sh                   — hoziroq bir marta tekshirish
# =====================================================================
set -euo pipefail

PAPKA="${TB_PAPKA:-/root/BacendDepoTb-}"
BRANCH="${TB_BRANCH:-main}"
ORALIQ="${TB_ORALIQ:-2min}"          # tekshirish oraligʻi (systemd formati)

# ---------------------------------------------------------------------
# Oʻrnatish rejimi — systemd service + timer yaratadi
# ---------------------------------------------------------------------
if [ "${1:-}" = "ornat" ]; then
  echo "[tb] Avto-yangilanish oʻrnatilmoqda: $PAPKA ($BRANCH), har $ORALIQ"

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
  echo "[tb] Tayyor. Holat:"
  systemctl status tb-yangila.timer --no-pager | head -5
  exit 0
fi

# ---------------------------------------------------------------------
# Oddiy rejim — bir marta tekshirib, kerak boʻlsa yangilaydi
# ---------------------------------------------------------------------
cd "$PAPKA"

git fetch --quiet origin "$BRANCH"
JORIY="$(git rev-parse HEAD)"
YANGI="$(git rev-parse "origin/$BRANCH")"

if [ "$JORIY" = "$YANGI" ]; then
  echo "[tb] Yangilik yoʻq ($(echo "$JORIY" | cut -c1-7))"
  exit 0
fi

echo "[tb] Yangi commit: $(echo "$JORIY" | cut -c1-7) → $(echo "$YANGI" | cut -c1-7)"
git reset --hard "origin/$BRANCH"

# .env.production serverda yaratiladi va repoda yoʻq — mavjud boʻlsa
# ishlatamiz, boʻlmasa docker compose oʻz standartlari bilan koʻtaradi.
if [ -f .env.production ]; then
  docker compose --env-file .env.production up -d --build
else
  docker compose up -d --build
fi

# Eski image'lar diskni toʻldirmasin (volume'larga tegilmaydi — baza xavfsiz)
docker image prune -f >/dev/null 2>&1 || true

echo "[tb] Yangilandi: $(git log -1 --pretty='%h %s')"
