"""
InventoryReport — the one payload every collector produces (agent, WinRM, WMI,
SSH, SNMP, hypervisor and cloud connectors) and InventoryService ingests.

Section semantics: a section that is `None` was *not collected* by this
collector, so existing data for it is left alone. An empty list means it *was*
collected and is empty (e.g. no software installed). This lets partial
collectors (SNMP knows no software) report without wiping what others found.

Vendor-formatted dates (WMI's "1/15/2024", "20240115", …) are kept as strings
here and normalised on ingest.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 2

_S = Optional[str]


class _Section(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Hardware(_Section):
    manufacturer: _S = None
    model: _S = None
    serial_number: _S = None
    hardware_uuid: _S = None            # SMBIOS system UUID
    chassis_type: _S = None             # desktop, laptop, server, vm, …
    is_virtual: Optional[bool] = None
    cpu: _S = None
    cpu_cores: Optional[int] = None
    cpu_logical: Optional[int] = None
    ram_gb: Optional[float] = None
    disk_gb: Optional[float] = None     # total fixed-disk capacity
    bios_vendor: _S = None
    bios_version: _S = None
    bios_date: _S = None
    motherboard: _S = None


class SoftwareItem(_Section):
    name: str = Field(min_length=1, max_length=500)
    version: _S = None
    publisher: _S = None
    install_date: _S = None


class PatchItem(_Section):
    id: str = Field(min_length=1, max_length=128)   # KB5034441, or package@version on Unix
    description: _S = None
    installed_on: _S = None


class ServiceItem(_Section):
    name: str = Field(min_length=1, max_length=255)
    display_name: _S = None
    state: _S = None          # running, stopped, …
    start_mode: _S = None     # auto, manual, disabled
    account: _S = None


class LocalAccount(_Section):
    name: str = Field(min_length=1, max_length=255)
    enabled: Optional[bool] = None
    is_admin: Optional[bool] = None
    last_logon: _S = None


class AntivirusProduct(_Section):
    name: str
    enabled: Optional[bool] = None
    up_to_date: Optional[bool] = None
    definitions_date: _S = None


class FirewallProfile(_Section):
    profile: str              # domain/private/public on Windows; "default" elsewhere
    enabled: Optional[bool] = None


class EncryptedVolume(_Section):
    volume: str
    method: _S = None         # BitLocker, FileVault, LUKS
    protected: Optional[bool] = None
    status: _S = None


class Security(_Section):
    antivirus: Optional[List[AntivirusProduct]] = None
    firewall: Optional[List[FirewallProfile]] = None
    encryption: Optional[List[EncryptedVolume]] = None
    tpm_present: Optional[bool] = None
    tpm_ready: Optional[bool] = None
    secure_boot: Optional[bool] = None


class Disk(_Section):
    name: str                 # C:, /, /home
    filesystem: _S = None
    size_gb: Optional[float] = None
    free_gb: Optional[float] = None


class NetworkAdapter(_Section):
    name: str
    mac: _S = None
    ip_addresses: List[str] = Field(default_factory=list)
    speed_mbps: Optional[int] = None
    dhcp: Optional[bool] = None
    gateway: _S = None
    dns_servers: List[str] = Field(default_factory=list)


class Monitor(_Section):
    manufacturer: _S = None
    model: _S = None
    serial_number: _S = None


class Printer(_Section):
    name: str
    driver: _S = None
    port: _S = None
    is_network: Optional[bool] = None
    is_default: Optional[bool] = None


class InventoryReport(_Section):
    schema_version: int = SCHEMA_VERSION
    collector_version: _S = None      # agent / scanner build that produced this

    # Identity & OS
    hostname: _S = None
    fqdn: _S = None
    domain: _S = None
    os_name: _S = None
    os_version: _S = None
    os_build: _S = None
    architecture: _S = None
    last_boot: _S = None
    logged_in_user: _S = None
    ip_addresses: List[str] = Field(default_factory=list, max_length=256)
    mac_addresses: List[str] = Field(default_factory=list, max_length=256)

    # Sections (None = not collected)
    hardware: Optional[Hardware] = None
    software: Optional[List[SoftwareItem]] = Field(default=None, max_length=10_000)
    patches: Optional[List[PatchItem]] = Field(default=None, max_length=5_000)
    services: Optional[List[ServiceItem]] = Field(default=None, max_length=2_000)
    local_accounts: Optional[List[LocalAccount]] = Field(default=None, max_length=1_000)
    security: Optional[Security] = None
    disks: Optional[List[Disk]] = Field(default=None, max_length=256)
    network_adapters: Optional[List[NetworkAdapter]] = Field(default=None, max_length=256)
    monitors: Optional[List[Monitor]] = Field(default=None, max_length=64)
    printers: Optional[List[Printer]] = Field(default=None, max_length=256)
    pending_reboot: Optional[bool] = None

    @classmethod
    def from_v1(cls, v1: dict) -> "InventoryReport":
        """The flat payload agents sent before schema_version existed."""
        return cls(
            schema_version=SCHEMA_VERSION,
            collector_version="v1",
            hostname=v1.get("hostname"),
            fqdn=v1.get("fqdn"),
            domain=v1.get("domain"),
            os_name=v1.get("os_name"),
            os_version=v1.get("os_version"),
            logged_in_user=v1.get("logged_in_user"),
            ip_addresses=v1.get("ip_addresses") or [],
            mac_addresses=v1.get("mac_addresses") or [],
            hardware=Hardware(
                manufacturer=v1.get("manufacturer"),
                model=v1.get("model"),
                serial_number=v1.get("serial_number"),
                hardware_uuid=v1.get("machine_id"),
                cpu=v1.get("cpu"),
                ram_gb=v1.get("ram_gb"),
                disk_gb=v1.get("disk_gb"),
            ),
            # v1 always sent the full list, so it counts as collected.
            software=v1.get("software") or [],
        )
