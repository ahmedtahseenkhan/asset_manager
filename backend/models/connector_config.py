from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from backend.database import Base
from backend.utils.encryption import EncryptedJSON
class ConnectorConfig(Base):
    __tablename__ = "connector_configs"

    id = Column(Integer, primary_key=True, index=True)
    connector_name = Column(String(100), unique=True, index=True, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    config = Column(EncryptedJSON, default=dict, nullable=False) # Stores connection configs/secrets ideally encrypted
    schedule_cron = Column(String(100), default="0 */6 * * *") # Every 6 hours
    last_run = Column(DateTime(timezone=True))
    last_status = Column(String(50)) # success, failed, running

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
