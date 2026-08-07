import random
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from backend.connectors.base import BaseConnector, RawDeviceRecord

class MockConnector(BaseConnector):
    name = "mock"
    display_name = "Mock / Dev Data"

    async def test_connection(self, config: Dict[str, Any]) -> bool:
        # Simulate network latency
        await asyncio.sleep(1)
        return True

    async def fetch_devices(self, config: Dict[str, Any]) -> List[RawDeviceRecord]:
        await asyncio.sleep(2)  # Simulate API delay
        count = int(config.get("device_count", 500))
        
        devices: List[RawDeviceRecord] = []
        os_options = [
            ("Microsoft Windows 11 Enterprise", "10.0.22621"),
            ("Microsoft Windows 10 Pro", "10.0.19045"),
            ("Ubuntu Linux", "22.04 LTS"),
            ("Red Hat Enterprise Linux", "8.6"),
            ("macOS Sonoma", "14.2"),
        ]
        
        ou_options = ["IT", "HR", "Engineering", "Finance", "Sales"]
        
        for i in range(count):
            os_name, os_version = random.choice(os_options)
            prefix = "WS" if "Windows" in os_name or "macOS" in os_name else "SVR"
            dept = random.choice(ou_options)
            hostname = f"{prefix}-{dept[:3].upper()}-{str(i).zfill(3)}"
            
            # 10% chance it's stale (last seen > 30 days)
            days_ago = random.randint(31, 100) if random.random() < 0.1 else random.randint(0, 10)
            
            devices.append({
                "source_uid": str(uuid.uuid4()),
                "hostname": hostname,
                "fqdn": f"{hostname}.testlab.local",
                "ip_addresses": [f"192.168.{random.randint(1,254)}.{random.randint(1,254)}"],
                "mac_addresses": [f"00:1A:2B:3C:{random.randint(10,99)}:{random.randint(10,99)}"],
                "os_name": os_name,
                "os_version": os_version,
                "domain": "testlab.local",
                "ou": f"OU={dept},DC=testlab,DC=local",
                "last_seen": datetime.now(timezone.utc) - timedelta(days=days_ago),
                "extra": {
                    "is_virtual": random.choice([True, False]),
                    "agent_version": f"2.4.{random.randint(1, 9)}"
                }
            })
            
        return devices

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "required": ["device_count"],
            "properties": {
                "device_count": {
                    "type": "integer",
                    "title": "Device Count",
                    "default": 500,
                    "description": "Number of mock devices to generate"
                }
            }
        }
