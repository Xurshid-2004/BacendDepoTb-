#!/bin/sh
# =====================================================================
# Bazani zaxiralash — droplet ichida ishlaydi.
#
#   ./backup.sh              # /root/tb-backup papkasiga yozadi
#
# Har kuni soat 3:00 da avtomatik bajarish (droplet ichida):
#   crontab -e
#   0 3 * * * cd /root/BacendDepoTb- && ./backup.sh >> /var/log/tb-backup.log 2>&1
#
# Tiklash:
#   gunzip -c /root/tb-backup/tb-2026-08-17.sql.gz | \
#     docker compose exec -T db psql -U tb -d tb
# =====================================================================
set -e

PAPKA="${TB_BACKUP_DIR:-/root/tb-backup}"
SAQLASH_KUN="${TB_BACKUP_KEEP:-14}"
SANA="$(date +%F)"

mkdir -p "$PAPKA"

# .env.production dan foydalanuvchi/baza nomini olamiz
FOYDALANUVCHI="$(grep -E '^POSTGRES_USER=' .env.production | cut -d= -f2- || true)"
BAZA="$(grep -E '^POSTGRES_DB=' .env.production | cut -d= -f2- || true)"
FOYDALANUVCHI="${FOYDALANUVCHI:-tb}"
BAZA="${BAZA:-tb}"

echo "[tb] Zaxira: $PAPKA/tb-$SANA.sql.gz"
docker compose --env-file .env.production exec -T db \
  pg_dump -U "$FOYDALANUVCHI" -d "$BAZA" | gzip > "$PAPKA/tb-$SANA.sql.gz"

# Eski nusxalarni tozalash
find "$PAPKA" -name 'tb-*.sql.gz' -mtime +"$SAQLASH_KUN" -delete

echo "[tb] Tayyor."
