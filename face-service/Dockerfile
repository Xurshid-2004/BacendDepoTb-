FROM python:3.11-slim

# DIQQAT — model qayerda saqlanadi:
#   insightface 1.0.1 `INSIGHTFACE_HOME` ni EʼTIBORSIZ qoldiradi va modelni
#   doim `$HOME/.insightface/models` ga yuklaydi. Shuning uchun compose'dagi
#   volume ham aynan shu yoʻlga ulanadi (/root/.insightface).
#   Oʻzgaruvchi kelajakdagi versiyalar uchun qoldirilgan.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/root \
    INSIGHTFACE_HOME=/root/.insightface

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelni image ichiga oldindan yuklab qoʻyish (birinchi soʻrov tez boʻlishi uchun)
RUN python -c "from insightface.app import FaceAnalysis; \
    m=FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
    m.prepare(ctx_id=0, det_size=(640,640))" || true

COPY app.py run.py ./

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/health" || exit 1

# Port, host va workerlar soni run.py da belgilanadi (u PORT oʻzgaruvchisini
# Python tomonida oʻqiydi). Buyruqda oʻzgaruvchi qolmagani uchun exec shakli
# xavfsiz: platforma buyruqni shellsiz uzatganda ham "$PORT" matn holida
# qolib ketmaydi.
CMD ["python", "run.py"]
