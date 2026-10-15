from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


class SshHostKey(Base):
    """Trusted SSH host key per address (trust on first use). Credentials are
    never sent to a host whose key no longer matches; an admin must review and
    clear the stored key first."""
    __tablename__ = "ssh_host_keys"

    id = Column(Integer, primary_key=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=22)
    key_type = Column(String(64), nullable=False)
    public_key = Column(Text, nullable=False)          # OpenSSH format
    fingerprint = Column(String(128), nullable=False)  # SHA256:…
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("host", "port", name="uq_ssh_host_key"),)
