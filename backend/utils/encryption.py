import json
from sqlalchemy.types import TypeDecorator, String
from cryptography.fernet import Fernet, InvalidToken
import logging

logger = logging.getLogger(__name__)


def _load_fernet() -> Fernet:
    """
    Load Fernet from settings.
    - Production (DEBUG=false): raises immediately if key is missing or invalid.
    - Development (DEBUG=true): generates a session-scoped key and warns.
      Data encrypted with the session key cannot be decrypted after a restart,
      so set ENCRYPTION_KEY in .env even for local development.
    """
    from backend.config import settings
    if not settings.encryption_key:
        if not settings.debug:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        # Debug fallback — ephemeral key, data unreadable after restart
        logger.warning(
            "ENCRYPTION_KEY is not set. Using a temporary session key — "
            "connector credentials will be lost on restart. Set ENCRYPTION_KEY in .env."
        )
        return Fernet(Fernet.generate_key())
    try:
        return Fernet(settings.encryption_key.encode())
    except Exception as exc:
        raise RuntimeError(f"ENCRYPTION_KEY is invalid: {exc}") from exc


class EncryptedJSON(TypeDecorator):
    """Encrypts JSON column using Fernet symmetric encryption."""
    impl = String
    cache_ok = True

    def __init__(self, key: str | bytes = None):
        super().__init__()
        self.fernet = _load_fernet()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        json_str = json.dumps(value)
        return self.fernet.encrypt(json_str.encode("utf-8")).decode("utf-8")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            decrypted = self.fernet.decrypt(value.encode("utf-8"))
            return json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError) as e:
            logger.warning(f"Failed to decrypt EncryptedJSON: {e}")
            # Fallback for rows that were stored as plain JSON before encryption was enabled
            try:
                return json.loads(value)
            except Exception:
                return {}
