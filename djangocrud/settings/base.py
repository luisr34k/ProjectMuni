from pathlib import Path
import os
from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key")  # override en prod
DEBUG = False  # override en dev/prod

ALLOWED_HOSTS = []  # override en dev/prod

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
    "widget_tweaks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # estáticos en prod
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "dashboard.middleware.current_user.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "djangocrud.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ],
    },
}]

WSGI_APPLICATION = "djangocrud.wsgi.application"

# —— Archivos estáticos y media ——
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "dashboard" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"               
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# —— i18n ——
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# —— Mensajes Bootstrap ——
MESSAGE_TAGS = {
    messages.DEBUG: "secondary",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}

# —— Auth ——
AUTH_USER_MODEL = "dashboard.Usuario"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# —— Límites de subida ——
EVIDENCIA_MAX_MB = 5
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# —— Recurrente (siempre desde env; no hardcode) ——
RECURRENTE_PUBLIC_KEY = os.getenv("RECURRENTE_PUBLIC_KEY", "")
RECURRENTE_SECRET_KEY = os.getenv("RECURRENTE_SECRET_KEY", "")

# EMAIL: define por entorno (console en dev, SMTP en prod)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@muni-sanluis.gt")
