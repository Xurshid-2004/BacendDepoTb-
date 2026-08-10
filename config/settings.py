"""
=====================================================================
TB tizimi — Django sozlamalari (production darajada)

Barcha maxfiy qiymatlar muhit oʻzgaruvchilaridan (.env) olinadi.
Hech qanday parol/kalit shu faylga yozilmaydi.

Ishga tushirish:
    dev   : python manage.py runserver
    prod  : gunicorn config.wsgi:application
=====================================================================
"""

from pathlib import Path
import os
import sys

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# .env faylini yuklaymiz — avval Bacend/.env, keyin loyiha ildizidagi .env
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env", override=False)


# ---------------------------------------------------------------------
# Yordamchilar — muhit oʻzgaruvchilarini oʻqish
# ---------------------------------------------------------------------

def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def env_bool(key: str, default: bool = False) -> bool:
    raw = env(key, "1" if default else "0").lower()
    return raw in ("1", "true", "yes", "on", "ha")


def env_list(key: str, default: str = "") -> list[str]:
    return [x.strip() for x in env(key, default).split(",") if x.strip()]


# ---------------------------------------------------------------------
# Asosiy
# ---------------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", False)

# Testlar va boshqaruv buyruqlari uchun DEBUG rejimida zaxira kalit ishlatiladi,
# productionda esa kalit majburiy — boʻlmasa ilova umuman ishga tushmaydi.
SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-faqat-dev-uchun-productionda-ishlatilmaydi"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY sozlanmagan. Production uchun majburiy.\n"
            "Yaratish: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )

# JWT imzo kaliti — alohida boʻlgani maʼqul, boʻlmasa SECRET_KEY ishlatiladi
JWT_SECRET = env("JWT_SECRET") or SECRET_KEY
JWT_ACCESS_MIN = int(env("JWT_ACCESS_MIN", "30") or 30)
JWT_REFRESH_DAYS = int(env("JWT_REFRESH_DAYS", "30") or 30)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if DEBUG else "")
if not ALLOWED_HOSTS and DEBUG:
    ALLOWED_HOSTS = ["*"]

# Hosting platformasi oʻz domenini muhit oʻzgaruvchisida beradi
# (Render: tb-api.onrender.com, Railway: tb-api.up.railway.app).
# Uni qoʻlda yozib qoʻyish shart emas — deploy'da domen oʻzgarsa ham ishlaydi.
_platform_host = env("RENDER_EXTERNAL_HOSTNAME") or env("RAILWAY_PUBLIC_DOMAIN")
if _platform_host and _platform_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_platform_host)

# Depo kodi — bitta oʻrnatma bitta depoga xizmat qiladi
DEPO_KOD = env("NEXT_PUBLIC_DEPO_KOD", "TCH-6")


# ---------------------------------------------------------------------
# Ilovalar
# ---------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "corsheaders",

    "core",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ---------------------------------------------------------------------
# Maʼlumotlar bazasi — PostgreSQL
# ---------------------------------------------------------------------
# DATABASE_URL berilsa oʻsha ishlatiladi (docker-compose shuni beradi),
# aks holda alohida POSTGRES_* oʻzgaruvchilaridan yigʻiladi.

DATABASE_URL = env("DATABASE_URL")

if DATABASE_URL.startswith("sqlite"):
    # Faqat lokal ishlab chiqish uchun — productionda PostgreSQL ishlatiladi.
    _yol = DATABASE_URL.split("://", 1)[1] or "db.sqlite3"
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / _yol.lstrip("/"),
        }
    }
elif DATABASE_URL:
    from urllib.parse import parse_qs, urlparse, unquote

    _u = urlparse(DATABASE_URL)
    _q = parse_qs(_u.query)

    # Boshqarilayotgan bazalar (Render, Railway, Neon, Supabase) tashqi
    # ulanish uchun SSL talab qiladi va buni URL'ning `?sslmode=require`
    # qismida beradi. Uni oʻqimasak "SSL connection is required" xatosi
    # chiqadi. DB_SSLMODE bilan majburan ham belgilash mumkin.
    _sslmode = env("DB_SSLMODE") or (_q.get("sslmode") or [""])[0]

    _options: dict[str, str] = {}
    if _sslmode:
        _options["sslmode"] = _sslmode

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (_u.path or "/tb").lstrip("/"),
            "USER": unquote(_u.username or "tb"),
            "PASSWORD": unquote(_u.password or ""),
            "HOST": _u.hostname or "127.0.0.1",
            "PORT": str(_u.port or 5432),
            "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "600") or 600),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": _options,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "tb"),
            "USER": env("POSTGRES_USER", "tb"),
            "PASSWORD": env("POSTGRES_PASSWORD"),
            "HOST": env("POSTGRES_HOST", "127.0.0.1"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
        }
    }

# Testlarda tez ishlashi uchun SQLite (baza serveri talab qilinmaydi)
if "test" in sys.argv:
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tizim foydalanuvchisi — tabel raqami boʻyicha kiradi (username emas)
AUTH_USER_MODEL = "core.Worker"


# ---------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "api.errors.exception_handler",
    # 800 foydalanuvchi uchun himoya — kirish urinishlarini cheklash
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": env("THROTTLE_LOGIN", "20/min"),
        "write": env("THROTTLE_WRITE", "240/min"),
    },
}

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )


# ---------------------------------------------------------------------
# CORS — Next.js frontend boshqa portdan/domendan murojaat qiladi
# ---------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000" if DEBUG else "",
)
CORS_ALLOW_CREDENTIALS = False  # token Authorization sarlavhasida ketadi, cookie emas
CORS_ALLOW_HEADERS = [
    "accept", "accept-encoding", "authorization", "content-type",
    "dnt", "origin", "user-agent", "x-csrftoken", "x-requested-with",
]

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")
if _platform_host:
    # Django admin paneliga kirish uchun kerak (POST forma CSRF tekshiruvi)
    _platform_origin = f"https://{_platform_host}"
    if _platform_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_platform_origin)


# ---------------------------------------------------------------------
# Xavfsizlik (production)
# ---------------------------------------------------------------------

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)  # Caddy oldida — odatda False
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "31536000") or 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# Yuklanadigan hajm chegarasi — FaceID surati base64 holida keladi
DATA_UPLOAD_MAX_MEMORY_SIZE = int(env("DATA_UPLOAD_MAX_MB", "25") or 25) * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE


# ---------------------------------------------------------------------
# FaceID xizmati (ixtiyoriy)
# ---------------------------------------------------------------------
# URL boʻsh boʻlsa yuz tanish oʻchiq — tizim faqat PIN bilan ishlaydi.
# Yoqish: docker compose --profile face up -d --build

FACE_SERVICE_URL = env("FACE_SERVICE_URL")
FACE_SERVICE_TOKEN = env("FACE_SERVICE_TOKEN")
# Moslik chegarasi (0..1). Baland qiymat — qatʼiyroq.
FACE_THRESHOLD = float(env("FACE_THRESHOLD", "0.62") or 0.62)
# Servis javobini shuncha kutamiz — kutish kirishni bloklamasligi kerak
FACE_TIMEOUT = int(env("FACE_TIMEOUT", "12") or 12)
# Roʻyxatdan oʻtishda va kirishda nechta kadr olinadi (jonlilik uchun ≥2)
FACE_FRAMES = int(env("FACE_FRAMES", "3") or 3)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]


# ---------------------------------------------------------------------
# Til / vaqt
# ---------------------------------------------------------------------

LANGUAGE_CODE = "uz"
TIME_ZONE = env("TZ", "Asia/Tashkent")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------
# Statik fayllar (admin panel uchun)
# ---------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------
# Loglar — serverda xatoni koʻrish uchun
# ---------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "oddiy": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "oddiy",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("LOG_LEVEL", "DEBUG" if DEBUG else "INFO"),
    },
    "loggers": {
        "django.db.backends": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "tb": {"level": env("LOG_LEVEL", "INFO"), "handlers": ["console"], "propagate": False},
    },
}

