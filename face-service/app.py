"""
TB Face servisi — yuz vektorlash va taqqoslash
InsightFace (buffalo_l) + FastAPI

Endpointlar:
  GET  /health          — holat
  POST /embed           — suratdan 512-oʻlchovli vektor
  POST /compare         — ikki vektor yoki surat + vektor taqqoslash
  POST /verify          — jonlilik (liveness) belgisi bilan tekshirish

Himoya: X-Face-Token sarlavhasi FACE_TOKEN muhit oʻzgaruvchisi bilan mos kelishi shart.
"""
import base64
import contextlib
import io
import logging
import os
import threading
import time
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

TOKEN = os.getenv("FACE_TOKEN", "")
THRESHOLD = float(os.getenv("FACE_THRESHOLD", "0.62"))
DET_SIZE = int(os.getenv("FACE_DET_SIZE", "640"))

# Bir vaqtda nechta kadr hisoblanadi.
#
# Nega chegara kerak: ONNX Runtime har ishchi oqim uchun alohida xotira
# arenasi ajratadi va uni QAYTARMAYDI. Oʻlchov (2 vCPU, 4 GB droplet):
#   model yuklangan, boʻsh — 458 MB
#   5 ta bir vaqtda        — 930 MB
#   20 ta bir vaqtda       — 1.68 GB   ← yuklama tugagach ham shu darajada qoladi
# Yaʼni har bir qoʻshimcha oqim ~61 MB. Chegarasiz qoldirilsa, uvicorn
# threadpool'i 40 tagacha koʻtaradi (~2.9 GB) va konteyner mem_limit
# (2.44 GB) dan oshib OOM bilan oʻladi.
#
# Hisob CPU'ga bogʻliq: 2 yadroda 20 ta bir vaqtdagi soʻrov baribir
# navbatda kutadi (bittasi 5.3 s). Yaʼni chegara oʻtkazuvchanlikni
# kamaytirmaydi — faqat xotira portlashining oldini oladi.
MAX_CONCURRENT = int(os.getenv("FACE_MAX_CONCURRENT", "4") or 4)

# Navbatda shuncha soniyadan ortiq kutgan soʻrov rad etiladi. Django
# tomonda FACE_TIMEOUT bor — u kutishni toʻxtatsa ham, biz hisoblashda
# davom etib bekorga CPU yeyishimiz mumkin edi. Tez «band» javobi
# yaxshiroq: Django PIN'ga oʻtadi va xodim tizimdan tashqarida qolmaydi.
QUEUE_TIMEOUT = float(os.getenv("FACE_QUEUE_TIMEOUT", "10") or 10)

_slot = threading.BoundedSemaphore(MAX_CONCURRENT)
_band = 0                       # hozir hisoblanayotgan soʻrovlar (/health uchun)
_band_qulf = threading.Lock()


@contextlib.contextmanager
def slot():
    """Hisoblash uchun joy band qiladi; navbat toʻlsa 503 qaytaradi."""
    global _band
    if not _slot.acquire(timeout=QUEUE_TIMEOUT):
        raise HTTPException(
            status_code=503,
            detail="Xizmat band — birozdan soʻng qayta urining yoki PIN bilan kiring",
        )
    with _band_qulf:
        _band += 1
    try:
        yield
    finally:
        with _band_qulf:
            _band -= 1
        _slot.release()

# buffalo_l paketida 5 ta model bor, lekin bizga faqat ikkitasi kerak:
#   detection   — yuzni topish (det_10g)
#   recognition — vektor olish (w600k_r50)
# Qolgani (yosh/jins, 3D nuqtalar) ishlatilmaydi, ammo yuklansa ~500 MB
# qoʻshimcha xotira yeydi. Railway'dagi eng qimmat resurs — aynan xotira.
MODULLAR = ["detection", "recognition"]

log = logging.getLogger("face")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Modelni fon oqimida oldindan yuklaydi ("warmup").

    Nega kerak: model() lazy edi — birinchi HAQIQIY soʻrov modelni
    yuklaguncha ~3 soniya kutardi. Yaʼni smena boshida birinchi xodim
    kamera oldida sababsiz turardi. Endi konteyner koʻtarilishi bilan
    yuklash boshlanadi va birinchi xodim ham tayyor modelga tushadi.

    Fon oqimida — uvicorn'ning ishga tushishini bloklamaslik uchun;
    tayyorlik holati /health orqali koʻrinadi.
    """
    def yukla():
        try:
            model()
        except Exception:
            log.exception("Isitish paytida model yuklanmadi")

    threading.Thread(target=yukla, name="warmup", daemon=True).start()
    yield


app = FastAPI(title="TB Face Service", version="1.0", lifespan=lifespan)

_model = None
_qulf = threading.Lock()
_holat = "kutmoqda"          # kutmoqda | yuklanmoqda | tayyor | xato


def model():
    """
    InsightFace modelini qaytaradi, kerak boʻlsa yuklaydi.

    Qulf shart: uvicorn sinxron endpointlarni threadpool'da bajaradi —
    qulfsiz ikkita bir vaqtdagi soʻrov modelni ikki marta yuklab,
    xotirani ikkilantirib yuborardi.
    """
    global _model, _holat
    if _model is not None:
        return _model

    with _qulf:
        if _model is None:
            from insightface.app import FaceAnalysis
            _holat = "yuklanmoqda"
            boshlandi = time.monotonic()
            try:
                m = FaceAnalysis(
                    name="buffalo_l",
                    providers=["CPUExecutionProvider"],
                    allowed_modules=MODULLAR,
                )
                m.prepare(ctx_id=0, det_size=(DET_SIZE, DET_SIZE))
            except Exception as e:
                _holat = "xato"
                log.error("Model yuklanmadi: %s", e)
                raise
            _model = m
            _holat = "tayyor"
            log.info("Model tayyor — %.1f soniya", time.monotonic() - boshlandi)
    return _model


def guard(token: Optional[str]):
    if TOKEN and token != TOKEN:
        raise HTTPException(status_code=401, detail="Ruxsat yoʻq")


def decode(image_b64: str) -> np.ndarray:
    from PIL import Image
    raw = image_b64.split(",", 1)[-1]          # data:image/...;base64,XXXX
    img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
    return np.array(img)[:, :, ::-1]           # RGB → BGR


def embed(image_b64: str):
    faces = model().get(decode(image_b64))
    if not faces:
        raise HTTPException(status_code=422, detail="Suratda yuz topilmadi")
    if len(faces) > 1:
        faces = sorted(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    f = faces[0]
    v = f.normed_embedding.astype(float)
    return v, f


def cosine(a: List[float], b: List[float]) -> float:
    x, y = np.array(a, dtype=float), np.array(b, dtype=float)
    return float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))


class EmbedIn(BaseModel):
    image: str                    # base64 (data URL ham boʻladi)


class CompareIn(BaseModel):
    image: Optional[str] = None
    vector: Optional[List[float]] = None
    target: List[float]           # bazadagi vektor
    threshold: Optional[float] = None


@app.get("/health")
def health():
    """
    Haqiqiy tayyorlik holati.

    Avval bu marshrut model yuklanmagan boʻlsa ham doim {"ok": true}
    qaytarardi — Docker konteynerni «healthy» deb belgilardi, holbuki u
    hali soʻrovga xizmat qila olmasdi. Endi holat rostini aytadi:
    model yuklanmaguncha 503, xato boʻlsa ham 503.
    """
    tayyor = _holat == "tayyor"
    tana = {
        "ok": tayyor,
        "holat": _holat,
        "model": "buffalo_l",
        "threshold": THRESHOLD,
        "band": _band,                           # hozir hisoblanayotgan soʻrovlar
        "max": MAX_CONCURRENT,
    }
    if not tayyor:
        raise HTTPException(status_code=503, detail=tana)
    return tana


@app.post("/embed")
def embed_route(body: EmbedIn, x_face_token: Optional[str] = Header(None)):
    guard(x_face_token)
    with slot():
        v, f = embed(body.image)
    return {
        "vector": v.tolist(),
        "bbox": [float(x) for x in f.bbox],
        "det_score": float(f.det_score),
        "sifat": "yaxshi" if f.det_score > 0.7 else "past",
    }


@app.post("/compare")
def compare_route(body: CompareIn, x_face_token: Optional[str] = Header(None)):
    guard(x_face_token)
    if body.vector is None and body.image is None:
        raise HTTPException(status_code=400, detail="image yoki vector kerak")
    if body.vector is not None:
        src = body.vector
    else:
        # Faqat surat berilganda hisoblash kerak — vektor tayyor boʻlsa
        # navbat band qilinmaydi (kosinus hisobi arzon).
        with slot():
            src = embed(body.image)[0].tolist()
    score = cosine(src, body.target)
    th = body.threshold if body.threshold is not None else THRESHOLD
    return {"score": round(score, 4), "threshold": th, "mos": score >= th}


class VerifyIn(BaseModel):
    frames: List[str]             # 2–3 kadr (jonlilik uchun)
    target: List[float]
    threshold: Optional[float] = None


@app.post("/verify")
def verify_route(body: VerifyIn, x_face_token: Optional[str] = Header(None)):
    """Bir nechta kadr: yuz har kadrda bor va vektorlar oʻzaro yaqin boʻlishi kerak
    (surat ekranga tutilganini qisman aniqlaydi)."""
    guard(x_face_token)
    if len(body.frames) < 2:
        raise HTTPException(status_code=400, detail="Kamida 2 kadr kerak")

    # Bitta kirish = bir necha kadr. Navbat bir marta band qilinadi:
    # kadrlar orasida joyni boʻshatsak, boshqa soʻrov oraga tushib
    # kirish yarim yoʻlda «band» xatosiga uchrashi mumkin edi.
    vectors, scores = [], []
    with slot():
        for fr in body.frames:
            v, f = embed(fr)
            vectors.append(v.tolist())
            scores.append(float(f.det_score))

    th = body.threshold if body.threshold is not None else THRESHOLD
    mos_list = [cosine(v, body.target) for v in vectors]
    ozaro = [cosine(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]

    # Kadrlar butunlay bir xil boʻlsa (score ≈ 1.0) — statik surat ehtimoli
    jonli = all(o > 0.80 for o in ozaro) and not all(o > 0.999 for o in ozaro)

    return {
        "mos": min(mos_list) >= th,
        "score": round(float(np.mean(mos_list)), 4),
        "min_score": round(min(mos_list), 4),
        "jonli": jonli,
        "det_scores": [round(s, 3) for s in scores],
        "threshold": th,
    }
