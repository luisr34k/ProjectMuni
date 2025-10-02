from .base import *
import os
import dj_database_url

DEBUG = False

# SECRET_KEY obligatorio en prod
SECRET_KEY = os.environ["SECRET_KEY"]

# Hosts/CSRF (Render)
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS = [f"https://{RENDER_EXTERNAL_HOSTNAME}"]

# DB: DATABASE_URL inyectado por Render (o defínelo manual)
DATABASES = {
    "default": dj_database_url.config(conn_max_age=600, ssl_require=True)
}

# SSL/Cookies detrás de proxy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# (opcional) SECURE_SSL_REDIRECT = True

# Email SMTP (p.ej. SendGrid / Mailgun)
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("SMTP_HOST", "smtp.sendgrid.net")
EMAIL_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("SMTP_USER", "apikey")
EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASS", "")
EMAIL_USE_TLS = True
