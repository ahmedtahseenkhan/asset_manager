from backend.database import Base
from backend.models.user import User
from backend.models.device import Device
from backend.models.device_source import DeviceSource
from backend.models.connector_config import ConnectorConfig
from backend.models.sync_log import SyncLog
from backend.models.app_license import AppLicenseActivation
from backend.models.asset import Asset, AssetLifecycleEvent
from backend.models.asset_relationship import AssetRelationship
from backend.models.contract import Contract
from backend.models.entitlement import Entitlement, EntitlementAssignment
from backend.models.notification import AlertRule, NotificationLog, SmtpSettings
from backend.models.agent import AgentToken
from backend.models.software import InstalledSoftware
from backend.models.vulnerability import Vulnerability
from backend.models.audit_log import AuditLog
from backend.models.scan_credential import ScanCredential
from backend.models.scan_target import ScanTarget, ScanTargetCredential
from backend.models.scan_run import ScanRun, ScanHostResult
from backend.models.ssh_host_key import SshHostKey
from backend.models.inventory import (
    DeviceInventory, DevicePatch, DeviceService, DeviceLocalAccount, DeviceAntivirus,
    DeviceVolume, DeviceNetworkAdapter, DeviceMonitor, DevicePrinter, DeviceChange,
)

__all__ = [
    "SshHostKey",
    "DeviceInventory", "DevicePatch", "DeviceService", "DeviceLocalAccount", "DeviceAntivirus",
    "DeviceVolume", "DeviceNetworkAdapter", "DeviceMonitor", "DevicePrinter", "DeviceChange",
    "AuditLog",
    "ScanCredential",
    "ScanTarget",
    "ScanTargetCredential",
    "ScanRun",
    "ScanHostResult",
    "AgentToken",
    "InstalledSoftware",
    "Vulnerability",
    "AlertRule",
    "NotificationLog",
    "SmtpSettings",
    "AssetRelationship",
    "Contract",
    "Entitlement",
    "EntitlementAssignment",
    "Base",
    "User",
    "Device",
    "DeviceSource",
    "ConnectorConfig",
    "SyncLog",
    "AppLicenseActivation",
    "Asset",
    "AssetLifecycleEvent",
]
