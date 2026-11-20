"""Settings for the single-collector web UI. Built for local use: DEBUG is on and only localhost is allowed."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # django_ui/
ROOT = BASE_DIR.parent  # the project folder: holds single_collector/, geocode.py, agent.py, .env, downloads/
os.chdir(ROOT)  # the pipeline reads and writes relative paths (downloads/, the Excel file, .env)
sys.path.insert(0, str(ROOT))  # so the views can import single_collector, geocode, agencies

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "local-development-only-change-before-sharing")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = ["django.contrib.contenttypes", "search"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

# Search jobs run the command-line pipeline in a separate process; this is how long one may take.
SEARCH_TIMEOUT_SECONDS = 30 * 60
DOWNLOADS_DIR = ROOT / "downloads"
