# =====================================================================
# TB tizimi — Django backend (production)
#
# Ishga tushirish gunicorn orqali. Migratsiyalar konteyner
# koʻtarilganda avtomatik bajariladi (docker-entrypoint.sh).
# =====================================================================

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# libpq — psycopg[binary] uchun kerak boʻlishi mumkin; curl — healthcheck uchun
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Root boʻlmagan foydalanuvchi
RUN useradd --create-home --uid 1001 tb \
 && mkdir -p /app/staticfiles /app/media \
 && chown -R tb:tb /app

COPY docker-entrypoint.sh /usr/local/bin/tb-entrypoint
RUN chmod +x /usr/local/bin/tb-entrypoint

USER tb
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/v1/health" || exit 1

ENTRYPOINT ["tb-entrypoint"]
# Port, workerlar soni va timeout — gunicorn.conf.py da belgilanadi
# (u PORT oʻzgaruvchisini Python tomonida oʻqiydi). Buyruqda oʻzgaruvchi
# qolmagani uchun exec shakli xavfsiz: platformalar buyruqni shellsiz
# uzatganda ham "$PORT" matn holida qolib ketmaydi.
CMD ["gunicorn", "config.wsgi:application"]
