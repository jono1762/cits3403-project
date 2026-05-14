# Single source of truth for Flask config. app/__init__.py wires this in via
# app.config.from_object(Config). Anything that depends on the environment
# (secrets, DB URL) reads from os.environ here; everything else stays a plain
# Python constant.
import os


class Config:
    # Path of this file's directory — same as Flask's app.root_path since
    # this module lives at the root of the app/ package.
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Pulled from .env (see .env.example). Falls back to an obvious dev
    # placeholder so the app still boots without a real secret set —
    # NEVER use the placeholder in production.
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-CHANGE-ME')

    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Media upload config — files saved to app/static/uploads/, served as /static/uploads/<filename>
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024   # 200 MB max per request


# Tunables imported directly by the modules that use them. Module-level rather
# than on Config because nothing about them is request-scoped.
WEATHER_CACHE_TTL_MIN = 10            # how long a city's weather response is cached
WEATHER_API_TIMEOUT_S = 5             # max seconds to wait on Open-Meteo before giving up
FAVOURITES_TRENDING_THRESHOLD = 20    # active reports per city before the "trending" pill shows
