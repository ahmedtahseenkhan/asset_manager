from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class DeviceSourceOut(BaseModel):
    id: int
    source_name: str
    source_uid: Optional[str]
    raw_data: Dict[str, Any]
    last_synced: Optional[datetime]

    class Config:
        from_attributes = True

class DeviceOut(BaseModel):
    id: int
    hostname: Optional[str]
    fqdn: Optional[str]
    ip_addresses: List[str]
    mac_addresses: List[str]
    os_name: Optional[str]
    os_version: Optional[str]
    domain: Optional[str]
    ou: Optional[str]
    first_seen: datetime
    last_seen: Optional[datetime]
    status: str
    sources: List[DeviceSourceOut] = []

    class Config:
        from_attributes = True

class DeviceListOut(BaseModel):
    items: List[DeviceOut]
    total: int
    page: int
    size: int

class DeviceFilter(BaseModel):
    search: Optional[str] = None
    os_name: Optional[str] = None
    status: Optional[str] = None
