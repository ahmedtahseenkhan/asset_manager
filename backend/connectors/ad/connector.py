import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import ldap3
from backend.connectors.base import BaseConnector, RawDeviceRecord

logger = logging.getLogger(__name__)

class ActiveDirectoryConnector(BaseConnector):
    name = "ad"
    display_name = "Active Directory"

    def _get_connection(self, config: Dict[str, Any]) -> ldap3.Connection:
        server = ldap3.Server(config.get("server_url"))
        conn = ldap3.Connection(
            server,
            user=config.get("bind_dn"),
            password=config.get("bind_password"),
            auto_bind=True
        )
        return conn

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        def _test():
            try:
                conn = self._get_connection(config)
                conn.unbind()
                return True
            except Exception as e:
                logger.error(f"AD Test Connection Failed: {e}")
                return False
                
        return await asyncio.to_thread(_test)

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        def _fetch():
            devices: List[RawDeviceRecord] = []
            try:
                conn = self._get_connection(config)
                base_dn = config.get("search_base")
                
                # Search for computer objects
                search_filter = "(&(objectCategory=computer)(objectClass=computer))"
                attributes = [
                    "objectGUID", "name", "dNSHostName", "operatingSystem", 
                    "operatingSystemVersion", "whenCreated", "distinguishedName"
                ]
                
                conn.search(
                    search_base=base_dn,
                    search_filter=search_filter,
                    attributes=attributes,
                    search_scope=ldap3.SUBTREE
                )
                
                for entry in conn.entries:
                    # Parse GUID from bytes
                    guid_bytes = entry.objectGUID.value
                    if guid_bytes:
                        import uuid
                        guid = str(uuid.UUID(bytes_le=guid_bytes))
                    else:
                        guid = str(entry.name.value)
                        
                    dn = str(entry.distinguishedName.value)
                    # Extract OU from DN
                    ou_parts = [part for part in dn.split(",") if part.startswith("OU=")]
                    ou = ",".join(ou_parts) if ou_parts else None

                    # Basic AD parsing
                    devices.append({
                        "source_uid": guid,
                        "hostname": str(entry.name.value) if entry.name else None,
                        "fqdn": str(entry.dNSHostName.value) if entry.dNSHostName else None,
                        "ip_addresses": [], # AD rarely has reliable IPs in computer object
                        "mac_addresses": [],
                        "os_name": str(entry.operatingSystem.value) if 'operatingSystem' in entry else None,
                        "os_version": str(entry.operatingSystemVersion.value) if 'operatingSystemVersion' in entry else None,
                        "domain": config.get("domain_name"),
                        "ou": ou,
                        "last_seen": datetime.now(timezone.utc), # AD lastLogon is hard to parse accurately in basic script, using now for simplicity
                        "extra": {
                            "whenCreated": str(entry.whenCreated.value) if 'whenCreated' in entry else None,
                            "dn": dn
                        }
                    })
                    
                conn.unbind()
            except Exception as e:
                logger.error(f"AD Fetch Failed: {e}")
                
            return devices

        return await asyncio.to_thread(_fetch)

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["server_url", "bind_dn", "bind_password", "search_base", "domain_name"],
            "properties": {
                "server_url": {
                    "type": "string", 
                    "title": "LDAP Server URL", 
                    "default": "ldap://127.0.0.1:389"
                },
                "domain_name": {
                    "type": "string",
                    "title": "Domain Name",
                    "default": "testlab.local"
                },
                "bind_dn": {
                    "type": "string", 
                    "title": "Bind DN", 
                    "default": "CN=Administrator,CN=Users,DC=testlab,DC=local"
                },
                "bind_password": {
                    "type": "string", 
                    "title": "Bind Password", 
                    "format": "password",
                    "default": "P@ssw0rd123"
                },
                "search_base": {
                    "type": "string", 
                    "title": "Search Base", 
                    "default": "DC=testlab,DC=local"
                }
            }
        }
