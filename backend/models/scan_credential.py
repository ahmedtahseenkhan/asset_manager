from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from backend.database import Base
from backend.utils.encryption import EncryptedJSON


class ScanCredential(Base):
    """A credential the scanner may try against hosts (credential vault).

    `secret` holds passwords / keys / communities, Fernet-encrypted and never
    returned by the API. `params` holds non-secret settings (e.g. SNMPv3
    protocols) that the UI may show.
    """
    __tablename__ = "scan_credentials"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    cred_type = Column(String(32), nullable=False, index=True)   # see scanning.credentials.CREDENTIAL_TYPES
    username = Column(String(255))
    params = Column(JSON, nullable=False, default=dict)
    secret = Column(EncryptedJSON, nullable=False, default=dict)
    description = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
