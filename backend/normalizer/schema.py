from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class UnifiedDeviceRecord:
    """The canonical internal representation of a device after normalization."""
    hostname: Optional[str] = None
    fqdn: Optional[str] = None
    ip_addresses: List[str] = field(default_factory=list)
    mac_addresses: List[str] = field(default_factory=list)
    os_family: Optional[str] = None   # "Windows", "Linux", "macOS"
    os_version: Optional[str] = None  # "10", "11", "22.04"
    domain: Optional[str] = None
    ou: Optional[str] = None
    last_seen: Optional[datetime] = None
    status: str = "active"
