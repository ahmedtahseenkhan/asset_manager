from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent

# Typical Vite dev ports when 5173+ are already taken
_VITE_DEV_PORTS = range(5173, 5220)

_INSECURE_JWT_DEFAULTS = {
    "change-me-in-production-use-openssl-rand-hex-32",
    "secret",
    "changeme",
    "jwt_secret",
}


class Settings(BaseSettings):
    app_name: str = "IT Asset Management"
    debug: bool = False

    # Database
    database_url: str

    # Auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 480
    encryption_key: str | None = None

    # CORS (when debug=True, local Vite ports below are merged in automatically)
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        # Reject known-insecure JWT secrets in production
        if not self.debug and self.jwt_secret in _INSECURE_JWT_DEFAULTS:
            raise ValueError(
                "JWT_SECRET is set to a default/insecure value. "
                "Generate a secure secret with: openssl rand -hex 32"
            )
        if not self.debug and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")

        # Require encryption key in production
        if not self.debug and not self.encryption_key:
            raise ValueError(
                "ENCRYPTION_KEY is required in production. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

        # Merge Vite CORS origins in debug mode
        if self.debug:
            extras = [
                origin
                for p in _VITE_DEV_PORTS
                for origin in (
                    f"http://localhost:{p}",
                    f"http://127.0.0.1:{p}",
                )
            ]
            seen: set[str] = set()
            merged: List[str] = []
            for o in (*self.cors_origins, *extras):
                if o not in seen:
                    seen.add(o)
                    merged.append(o)
            self.cors_origins = merged

        return self


settings = Settings()
