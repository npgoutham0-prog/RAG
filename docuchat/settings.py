"""Django settings for the DocuChat project."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get(
    "DJANGO_DEBUG", "false" if os.environ.get("VERCEL") else "true"
).lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "django-insecure-local-docuchat-key" if DEBUG else ""
)
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY for production.")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"
    ).split(",")
    if host.strip()
]
VERCEL_HOSTS = [
    os.environ[name].strip()
    for name in (
        "VERCEL_URL",
        "VERCEL_BRANCH_URL",
        "VERCEL_PROJECT_PRODUCTION_URL",
    )
    if os.environ.get(name, "").strip()
]
ALLOWED_HOSTS.extend(host for host in VERCEL_HOSTS if host not in ALLOWED_HOSTS)
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS.extend(
    origin
    for origin in (f"https://{host}" for host in VERCEL_HOSTS)
    if origin not in CSRF_TRUSTED_ORIGINS
)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = urlsplit(OLLAMA_BASE_URL)
if not DEBUG and (
    OLLAMA_URL.scheme != "https"
    or not OLLAMA_URL.netloc
    or OLLAMA_URL.username is not None
    or OLLAMA_URL.password is not None
    or OLLAMA_URL.query
    or OLLAMA_URL.fragment
):
    raise ImproperlyConfigured(
        "Production OLLAMA_BASE_URL must be a valid HTTPS URL without credentials."
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "docuchat.urls"

TEMPLATES = [
    {
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
    },
]

WSGI_APPLICATION = "docuchat.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=0,
            ssl_require=True,
        )
    }
elif DEBUG:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise ImproperlyConfigured("Set DATABASE_URL to a persistent PostgreSQL database.")

SUPABASE_STORAGE_ENV = {
    "endpoint_url": os.environ.get("SUPABASE_S3_ENDPOINT_URL"),
    "region_name": os.environ.get("SUPABASE_S3_REGION"),
    "access_key": os.environ.get("SUPABASE_S3_ACCESS_KEY_ID"),
    "secret_key": os.environ.get("SUPABASE_S3_SECRET_ACCESS_KEY"),
    "bucket_name": os.environ.get("SUPABASE_STORAGE_BUCKET_NAME"),
}
DIRECT_UPLOADS_ENABLED = all(SUPABASE_STORAGE_ENV.values())
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
if DIRECT_UPLOADS_ENABLED:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            **SUPABASE_STORAGE_ENV,
            "addressing_style": "path",
            "signature_version": "s3v4",
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
        },
    }
elif not DEBUG:
    raise ImproperlyConfigured(
        "Set all Supabase S3 storage environment variables for production."
    )

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
