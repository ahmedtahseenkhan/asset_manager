from typing import Optional
from backend.connectors.base import RawDeviceRecord
from backend.normalizer.schema import UnifiedDeviceRecord

class Normalizer:
    @staticmethod
    def _normalize_os(raw_os: Optional[str], raw_version: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if not raw_os:
            return None, raw_version
            
        os_lower = raw_os.lower()
        os_family = None
        os_version = raw_version
        
        if "windows" in os_lower:
            os_family = "Windows"
            if "11" in os_lower:
                os_version = "11"
            elif "10" in os_lower:
                os_version = "10"
            elif "server" in os_lower:
                os_family = "Windows Server"
                if "2019" in os_lower: os_version = "2019"
                elif "2022" in os_lower: os_version = "2022"
        elif "linux" in os_lower or "ubuntu" in os_lower or "red hat" in os_lower:
            os_family = "Linux"
        elif "mac" in os_lower or "macos" in os_lower:
            os_family = "macOS"
            
        return os_family, os_version

    @staticmethod
    def _normalize_hostname(hostname: Optional[str]) -> Optional[str]:
        if not hostname:
            return None
        # Remove domain suffix if present in hostname
        if "." in hostname:
            hostname = hostname.split(".")[0]
        return hostname.upper()

    @staticmethod
    def normalize(source_name: str, raw: RawDeviceRecord) -> UnifiedDeviceRecord:
        """Transforms a RawDeviceRecord into a UnifiedDeviceRecord."""
        os_family, os_version = Normalizer._normalize_os(raw.get("os_name"), raw.get("os_version"))
        hostname = Normalizer._normalize_hostname(raw.get("hostname"))
        
        return UnifiedDeviceRecord(
            hostname=hostname,
            fqdn=raw.get("fqdn").lower() if raw.get("fqdn") else None,
            ip_addresses=list(set(raw.get("ip_addresses", []))),
            mac_addresses=[mac.upper() for mac in raw.get("mac_addresses", [])],
            os_family=os_family,
            os_version=os_version,
            domain=raw.get("domain").lower() if raw.get("domain") else None,
            ou=raw.get("ou"),
            last_seen=raw.get("last_seen"),
            status="active"
        )
