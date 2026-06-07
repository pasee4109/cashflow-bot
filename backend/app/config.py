"""
config.py — Application settings (environment driven)
=====================================================
All secrets are read from environment variables / .env so that
no credential is ever committed to source control.
"""

import base64
import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Core ────────────────────────────────────────────────────────
    app_name: str = "TFEX Cashflow Ladder"
    environment: str = "development"          # development | production
    debug: bool = True

    # ── Security / sessions ─────────────────────────────────────────
    # SECRET_KEY signs JWTs and the OAuth session cookie.
    secret_key: str = "dev-insecure-secret-change-me-0123456789-abcdefghijklmnop"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7      # 7 days

    # APP_ENCRYPTION_KEY must be a urlsafe-base64 32-byte Fernet key.
    # When blank we deterministically derive one from SECRET_KEY so dev
    # works out of the box — set a real key in production.
    encryption_key: str = ""

    # ── Google OAuth ────────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where Google redirects back to (must match the console config).
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # In development, allow a password-less dev login so the app is
    # usable before Google credentials are configured.
    allow_dev_login: bool = True

    # ── URLs ────────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:5173"
    cookie_secure: bool = False                # True behind HTTPS
    cookie_samesite: str = "lax"

    # ── Database ────────────────────────────────────────────────────
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"

    # ── Grid defaults ───────────────────────────────────────────────
    default_allocation_pct: int = 30
    default_grid_levels: int = 5
    default_buyback_ticks: int = 3
    default_ladder_weights: str = "1,2,3,4,5"
    atr_period: int = 14
    atr_grid_limit: float = 1.0

    # ── Monitor ─────────────────────────────────────────────────────
    order_poll_interval_sec: int = 5
    heartbeat_interval_sec: int = 60

    @property
    def fernet_key(self) -> bytes:
        """Return a valid Fernet key, deriving one from secret_key if unset."""
        if self.encryption_key:
            return self.encryption_key.encode()
        digest = hashlib.sha256(self.secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def ladder_weights(self) -> list[int]:
        return [int(x) for x in self.default_ladder_weights.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
