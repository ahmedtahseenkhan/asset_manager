from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Dict, Any

class ConnectorConfigBase(BaseModel):
    enabled: bool = False
    schedule_cron: str = "0 */6 * * *"
    config: Dict[str, Any] = {}

class ConnectorConfigCreate(ConnectorConfigBase):
    pass

class ConnectorConfigOut(ConnectorConfigBase):
    id: int
    connector_name: str
    last_run: Optional[datetime]
    last_status: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class ConnectorStatusOut(BaseModel):
    name: str
    display_name: str
    is_configured: bool
    is_enabled: bool
    last_run: Optional[datetime]
    last_status: Optional[str]
    schema_definition: Dict[str, Any] # JSON schema for the dynamic form
