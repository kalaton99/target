"""Centralized config loaded from environment."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "72"))

ENGINE_VERSION = os.environ.get("ENGINE_VERSION", "1.0.0")
SIGNUP_BONUS = int(os.environ.get("SIGNUP_BONUS", "10000"))
RNG_ENCRYPTION_KEY = os.environ["RNG_ENCRYPTION_KEY"]
