from typing import TypedDict, Optional, List, Dict, Any
from datetime import datetime
from abc import ABC, abstractmethod

class RawDeviceRecord(TypedDict):
    """Minimum contract every connector must return per device."""
    source_uid: str
    hostname: Optional[str]
    fqdn: Optional[str]
    ip_addresses: List[str]
    mac_addresses: List[str]
    os_name: Optional[str]
    os_version: Optional[str]
    domain: Optional[str]
    ou: Optional[str]
    last_seen: Optional[datetime]
    extra: Dict[str, Any]

class BaseConnector(ABC):
    """Abstract base class for all IT Asset Management connectors."""
    
    # These must be set by the implementing class
    name: str 
    display_name: str
    
    @abstractmethod
    async def test_connection(self, config: Dict[str, Any]) -> bool:
        """Test the connection using the provided configuration."""
        pass

    @abstractmethod
    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        """Fetch all devices from the source."""
        pass

    @abstractmethod
    def get_config_schema(self) -> Dict[str, Any]:
        """Return a JSON schema describing the required configuration fields."""
        pass
