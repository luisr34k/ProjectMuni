from .base import *
import os

DEBUG = True
ALLOWED_HOSTS = ["*"]

# DB local (sqlite)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Email a consola
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Cookies/SSL (no forzamos https en dev)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_PROXY_SSL_HEADER = None
# SECURE_SSL_REDIRECT = False
