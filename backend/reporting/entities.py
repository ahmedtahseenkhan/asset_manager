"""
What reports can query: a whitelist of entities, their joins and fields.

Nothing outside this file is reachable from a report definition — no raw SQL,
no arbitrary columns. Secrets (credential vault, license keys, password
hashes) are deliberately absent.

Field types and the operators they accept are defined in engine.OPERATORS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import case, exists, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import ColumnElement

from backend.models.asset import (
    ASSET_CATEGORIES, BACKUP_STATUS, CRITICALITY, DATA_CLASSIFICATION, LIFECYCLE_STATES, LOG_SOURCE_STATUS,
    MONITORING_STATUS, Asset,
)
from backend.models.contract import Contract
from backend.models.device import Device
from backend.models.entitlement import Entitlement
from backend.models.inventory import (
    CHANGE_CATEGORIES, DeviceAntivirus, DeviceChange, DeviceInventory, DeviceLocalAccount, DeviceMonitor,
    DevicePatch, DeviceService, DeviceVolume,
)
from backend.models.software import InstalledSoftware
from backend.models.virtualization import VmPlacement
from backend.models.vulnerability import SEVERITIES, Vulnerability


@dataclass
class Field:
    key: str
    label: str
    type: str                                 # string | number | date | datetime | bool | enum | list | relation
    expr: Optional[ColumnElement] = None      # selectable column (None for relation filters)
    choices: Optional[List[str]] = None       # enum values
    # relation filters: value -> EXISTS clause correlated to the entity's base row
    relation: Optional[Callable[[str], ColumnElement]] = None
    filter_only: bool = False


@dataclass
class Entity:
    key: str
    label: str
    base: type
    joins: List[Tuple[type, ColumnElement]]   # outer joins, in order
    fields: Dict[str, Field]
    default_columns: List[str]
    default_sort: str
    link: Optional[Tuple[str, ColumnElement]] = None   # ("device" | "asset", id expression) for row links
    module: Optional[str] = None                       # licence module the data belongs to
    description: str = ""
    category: str = "Inventory"
    # Fields a free-text search matches (any of them). Devices and assets mirror
    # their list pages; others default to their text-type default columns.
    search_fields: List[str] = field(default_factory=list)

    def searchable(self) -> List[Field]:
        keys = self.search_fields or [k for k in self.default_columns
                                      if self.fields[k].type in ("string", "list")]
        return [self.fields[k] for k in keys]


def _fields(*items: Field) -> Dict[str, Field]:
    return {f.key: f for f in items}


def _like(col, value: str):
    return col.ilike(f"%{value}%")


# ── shared device columns (for entities hanging off a device) ──────────────
def _device_fields() -> List[Field]:
    return [
        Field("hostname", "Hostname", "string", Device.hostname),
        Field("fqdn", "FQDN", "string", Device.fqdn),
        Field("device_status", "Device status", "enum", Device.status, ["active", "inactive", "retired"]),
        Field("os_family", "OS family", "string", Device.os_name),
        Field("domain", "Domain", "string", Device.domain),
        Field("device_last_seen", "Device last seen", "datetime", Device.last_seen),
    ]


_free_pct = case((DeviceVolume.size_gb > 0, DeviceVolume.free_gb * 100.0 / DeviceVolume.size_gb), else_=None)


def _has_software(v):
    return exists(select(InstalledSoftware.id).where(
        InstalledSoftware.device_id == Device.id, _like(InstalledSoftware.name, v)))


def _has_patch(v):
    return exists(select(DevicePatch.id).where(DevicePatch.device_id == Device.id, _like(DevicePatch.patch_id, v)))


def _has_service(v):
    return exists(select(DeviceService.id).where(
        DeviceService.device_id == Device.id,
        (DeviceService.name.ilike(f"%{v}%")) | (DeviceService.display_name.ilike(f"%{v}%"))))


def _has_admin(v):
    return exists(select(DeviceLocalAccount.id).where(
        DeviceLocalAccount.device_id == Device.id, DeviceLocalAccount.is_admin.is_(True),
        _like(DeviceLocalAccount.name, v)))


ENTITIES: Dict[str, Entity] = {}


def _register(e: Entity) -> None:
    ENTITIES[e.key] = e


def _asset_of_device(col):
    """A column of the asset linked to the device, as a scalar subquery so a
    device linked to several assets still yields one row."""
    return select(col).where(Asset.device_id == Device.id).order_by(Asset.id).limit(1).scalar_subquery()


# ── Devices ────────────────────────────────────────────────────────────────
_register(Entity(
    key="devices", label="Devices", base=Device, category="Inventory",
    description="Every discovered device with hardware, OS and security posture.",
    joins=[(DeviceInventory, DeviceInventory.device_id == Device.id)],
    link=("device", Device.id),
    default_columns=["hostname", "os_name", "manufacturer", "model", "last_seen", "status"],
    default_sort="hostname", search_fields=["hostname", "fqdn", "ip_addresses"],
    fields=_fields(
        Field("hostname", "Hostname", "string", Device.hostname),
        Field("fqdn", "FQDN", "string", Device.fqdn),
        Field("status", "Status", "enum", Device.status, ["active", "inactive", "retired"]),
        Field("ip_addresses", "IP addresses", "list", Device.ip_addresses),
        Field("mac_addresses", "MAC addresses", "list", Device.mac_addresses),
        Field("domain", "Domain", "string", Device.domain),
        Field("ou", "OU", "string", Device.ou),
        Field("serial_number", "Serial number", "string", Device.serial_number),
        Field("os_family", "OS family", "string", Device.os_name),
        Field("os_name", "Operating system", "string", DeviceInventory.os_name),
        Field("os_version", "OS version", "string", DeviceInventory.os_version),
        Field("os_build", "OS build", "string", DeviceInventory.os_build),
        Field("architecture", "Architecture", "string", DeviceInventory.architecture),
        Field("manufacturer", "Manufacturer", "string", DeviceInventory.manufacturer),
        Field("model", "Model", "string", DeviceInventory.model),
        Field("chassis_type", "Type", "string", DeviceInventory.chassis_type),
        Field("is_virtual", "Virtual", "bool", DeviceInventory.is_virtual),
        Field("cpu", "Processor", "string", DeviceInventory.cpu),
        Field("cpu_cores", "CPU cores", "number", DeviceInventory.cpu_cores),
        Field("ram_gb", "RAM (GB)", "number", DeviceInventory.ram_gb),
        Field("disk_gb", "Disk capacity (GB)", "number", DeviceInventory.disk_gb),
        Field("bios_version", "BIOS version", "string", DeviceInventory.bios_version),
        Field("logged_in_user", "Signed-in user", "string", DeviceInventory.logged_in_user),
        Field("last_boot", "Last boot", "datetime", DeviceInventory.last_boot),
        Field("pending_reboot", "Reboot pending", "bool", DeviceInventory.pending_reboot),
        Field("antivirus_ok", "Antivirus OK", "bool", DeviceInventory.antivirus_ok),
        Field("firewall_ok", "Firewall on", "bool", DeviceInventory.firewall_ok),
        Field("disk_encrypted", "Disk encrypted", "bool", DeviceInventory.disk_encrypted),
        Field("secure_boot", "Secure Boot", "bool", DeviceInventory.secure_boot),
        Field("tpm_present", "TPM present", "bool", DeviceInventory.tpm_present),
        Field("local_admin_count", "Local admins", "number", DeviceInventory.local_admin_count),
        Field("inventory_source", "Inventory source", "string", DeviceInventory.source),
        Field("collector_version", "Agent/collector version", "string", DeviceInventory.collector_version),
        Field("collected_at", "Inventory date", "datetime", DeviceInventory.collected_at),
        Field("first_seen", "First seen", "datetime", Device.first_seen),
        Field("last_seen", "Last seen", "datetime", Device.last_seen),
        Field("asset_tag", "Asset tag", "string", _asset_of_device(Asset.asset_tag)),
        Field("department", "Department (asset)", "string", _asset_of_device(Asset.department)),
        Field("location", "Location (asset)", "string", _asset_of_device(Asset.location)),
        Field("asset_owner", "Owner (asset)", "string", _asset_of_device(Asset.point_of_contact)),
        Field("criticality", "Criticality (asset)", "enum", _asset_of_device(Asset.criticality), CRITICALITY),
        Field("has_software", "Has software", "relation", relation=_has_software, filter_only=True),
        Field("has_patch", "Has update", "relation", relation=_has_patch, filter_only=True),
        Field("has_service", "Has service", "relation", relation=_has_service, filter_only=True),
        Field("has_local_admin", "Has local admin", "relation", relation=_has_admin, filter_only=True),
    ),
))


def _device_child(key, label, model, description, own: List[Field], default_columns, default_sort,
                  category="Inventory"):
    _register(Entity(
        key=key, label=label, base=model, category=category, description=description,
        joins=[(Device, Device.id == model.device_id)],
        link=("device", Device.id),
        default_columns=default_columns, default_sort=default_sort,
        fields=_fields(*own, *_device_fields()),
    ))


_device_child("software", "Installed software", InstalledSoftware,
              "Every application on every device (one row per install).",
              [Field("name", "Application", "string", InstalledSoftware.name),
               Field("version", "Version", "string", InstalledSoftware.version),
               Field("publisher", "Publisher", "string", InstalledSoftware.publisher),
               Field("normalized_name", "Product (normalized)", "string", InstalledSoftware.normalized_name),
               Field("last_seen", "Last seen", "datetime", InstalledSoftware.last_seen)],
              ["hostname", "name", "version", "publisher"], "name")

_device_child("patches", "Installed updates", DevicePatch,
              "Hotfixes (Windows) and software updates (macOS) per device.",
              [Field("patch_id", "Update", "string", DevicePatch.patch_id),
               Field("description", "Description", "string", DevicePatch.description),
               Field("installed_on", "Installed on", "date", DevicePatch.installed_on),
               Field("first_seen", "First seen", "datetime", DevicePatch.first_seen)],
              ["hostname", "patch_id", "description", "installed_on"], "installed_on")

_device_child("services", "Services", DeviceService, "Services and daemons per device.",
              [Field("name", "Service", "string", DeviceService.name),
               Field("display_name", "Display name", "string", DeviceService.display_name),
               Field("state", "State", "string", DeviceService.state),
               Field("start_mode", "Start mode", "string", DeviceService.start_mode),
               Field("account", "Runs as", "string", DeviceService.account)],
              ["hostname", "display_name", "state", "start_mode"], "name")

_device_child("local_accounts", "Local accounts", DeviceLocalAccount,
              "Local accounts and members of the local Administrators group.",
              [Field("name", "Account", "string", DeviceLocalAccount.name),
               Field("is_admin", "Admin", "bool", DeviceLocalAccount.is_admin),
               Field("enabled", "Enabled", "bool", DeviceLocalAccount.enabled),
               Field("last_logon", "Last sign-in", "datetime", DeviceLocalAccount.last_logon)],
              ["hostname", "name", "is_admin", "enabled", "last_logon"], "hostname", category="Security")

_device_child("antivirus", "Antivirus products", DeviceAntivirus, "Antivirus products reported per device.",
              [Field("name", "Product", "string", DeviceAntivirus.name),
               Field("enabled", "Enabled", "bool", DeviceAntivirus.enabled),
               Field("up_to_date", "Definitions current", "bool", DeviceAntivirus.up_to_date),
               Field("definitions_date", "Definitions date", "date", DeviceAntivirus.definitions_date)],
              ["hostname", "name", "enabled", "up_to_date"], "hostname", category="Security")

_device_child("volumes", "Disks & encryption", DeviceVolume, "Fixed volumes with capacity and encryption.",
              [Field("name", "Volume", "string", DeviceVolume.name),
               Field("filesystem", "File system", "string", DeviceVolume.filesystem),
               Field("size_gb", "Size (GB)", "number", DeviceVolume.size_gb),
               Field("free_gb", "Free (GB)", "number", DeviceVolume.free_gb),
               Field("free_pct", "Free (%)", "number", _free_pct),
               Field("encrypted", "Encrypted", "bool", DeviceVolume.encrypted),
               Field("encryption_method", "Encryption", "string", DeviceVolume.encryption_method)],
              ["hostname", "name", "size_gb", "free_pct", "encrypted"], "hostname")

_device_child("monitors", "Monitors", DeviceMonitor, "Displays attached to devices.",
              [Field("manufacturer", "Manufacturer", "string", DeviceMonitor.manufacturer),
               Field("model", "Model", "string", DeviceMonitor.model),
               Field("serial_number", "Serial number", "string", DeviceMonitor.serial_number)],
              ["hostname", "manufacturer", "model", "serial_number"], "hostname")

_device_child("changes", "Device changes", DeviceChange, "Change history from inventory reports.",
              [Field("detected_at", "Detected", "datetime", DeviceChange.detected_at),
               Field("category", "Category", "enum", DeviceChange.category, list(CHANGE_CATEGORIES)),
               Field("change_type", "Change", "enum", DeviceChange.change_type, ["added", "removed", "changed"]),
               Field("item", "Item", "string", DeviceChange.item),
               Field("field", "Attribute", "string", DeviceChange.field),
               Field("old_value", "Old value", "string", DeviceChange.old_value),
               Field("new_value", "New value", "string", DeviceChange.new_value),
               Field("severity", "Severity", "enum", DeviceChange.severity, ["info", "warning"]),
               Field("source", "Reported by", "string", DeviceChange.source)],
              ["detected_at", "hostname", "category", "change_type", "item", "old_value", "new_value"],
              "detected_at", category="Security")


# ── Virtual machines ───────────────────────────────────────────────────────
_VmHost = aliased(Device, name="vm_host")
_HYPERVISOR_SOURCES = ("hyperv", "vmware")

_register(Entity(
    key="virtual_machines", label="Virtual machines", base=VmPlacement, category="Inventory",
    description="Guests reported by their Hyper-V hosts: host, power state and allocation.",
    joins=[(Device, Device.id == VmPlacement.vm_device_id),
           (_VmHost, _VmHost.id == VmPlacement.host_device_id),
           (DeviceInventory, DeviceInventory.device_id == VmPlacement.vm_device_id)],
    link=("device", Device.id),
    default_columns=["vm_name", "host", "power_state", "guest_os", "vcpus", "memory_gb", "disk_gb"],
    default_sort="vm_name",
    search_fields=["vm_name", "hostname", "host", "guest_os"],
    fields=_fields(
        Field("vm_name", "Virtual machine", "string", VmPlacement.vm_name),
        Field("host", "Host", "string", _VmHost.hostname),
        Field("platform", "Platform", "enum", VmPlacement.platform, ["hyperv", "vmware"]),
        Field("power_state", "Power state", "enum", VmPlacement.power_state, ["on", "off", "suspended"]),
        Field("guest_os", "Guest OS", "string", VmPlacement.guest_os),
        Field("vcpus", "vCPUs", "number", VmPlacement.vcpus),
        Field("memory_gb", "Memory (GB)", "number", VmPlacement.memory_gb),
        Field("disk_gb", "Disk (GB)", "number", VmPlacement.disk_gb),
        Field("tools_status", "Integration services / tools", "string", VmPlacement.tools_status),
        Field("cluster", "Cluster", "string", VmPlacement.cluster),
        Field("datacenter", "Datacenter", "string", VmPlacement.datacenter),
        Field("own_inventory", "Own inventory (agent or scan)", "bool",
              case((DeviceInventory.source.is_(None), None),
                   (DeviceInventory.source.in_(_HYPERVISOR_SOURCES), False), else_=True)),
        Field("reported_at", "Reported by host", "datetime", VmPlacement.last_seen),
        *_device_fields(),
    ),
))


# ── Assets & commercial ────────────────────────────────────────────────────
_register(Entity(
    key="assets", label="Assets", base=Asset, category="Assets", module="assets",
    description="The asset register: lifecycle, ownership, cost, warranty and governance.",
    joins=[], link=("asset", Asset.id),
    default_columns=["asset_tag", "name", "category", "lifecycle_state", "department", "warranty_end"],
    default_sort="asset_tag", search_fields=["name", "asset_tag", "serial_number", "vendor", "model"],
    fields=_fields(
        Field("asset_tag", "Asset tag", "string", Asset.asset_tag),
        Field("name", "Name", "string", Asset.name),
        Field("category", "Category", "enum", Asset.category, ASSET_CATEGORIES),
        Field("asset_type", "Type", "string", Asset.asset_type),
        Field("lifecycle_state", "Lifecycle state", "enum", Asset.lifecycle_state, LIFECYCLE_STATES),
        Field("serial_number", "Serial number", "string", Asset.serial_number),
        Field("vendor", "Vendor", "string", Asset.vendor),
        Field("model", "Model", "string", Asset.model),
        Field("location", "Location", "string", Asset.location),
        Field("department", "Department", "string", Asset.department),
        Field("point_of_contact", "Owner / contact", "string", Asset.point_of_contact),
        Field("purchase_date", "Purchase date", "date", Asset.purchase_date),
        Field("purchase_cost", "Purchase cost", "number", Asset.purchase_cost),
        Field("warranty_end", "Warranty end", "date", Asset.warranty_end),
        Field("eol_eos_date", "End of life", "date", Asset.eol_eos_date),
        Field("os_name", "OS", "string", Asset.os_name),
        Field("ip_address", "IP address", "string", Asset.ip_address),
        Field("network_zone", "Network zone", "string", Asset.network_zone),
        Field("criticality", "Criticality", "enum", Asset.criticality, CRITICALITY),
        Field("data_classification", "Data classification", "enum", Asset.data_classification, DATA_CLASSIFICATION),
        Field("compliance", "Compliance", "string", Asset.compliance),
        Field("log_source_status", "Log source", "enum", Asset.log_source_status, LOG_SOURCE_STATUS),
        Field("monitoring_status", "Monitoring", "enum", Asset.monitoring_status, MONITORING_STATUS),
        Field("backup_status", "Backup", "enum", Asset.backup_status, BACKUP_STATUS),
        Field("last_vulnerability_scan", "Last vulnerability scan", "date", Asset.last_vulnerability_scan),
        Field("last_reviewed_date", "Last reviewed", "date", Asset.last_reviewed_date),
        Field("reviewer", "Reviewer", "string", Asset.reviewer),
        Field("has_device", "Linked to a device", "bool", Asset.device_id.isnot(None)),
        Field("created_at", "Created", "datetime", Asset.created_at),
    ),
))

_register(Entity(
    key="vulnerabilities", label="Vulnerabilities", base=Vulnerability, category="Security",
    description="Imported scanner findings, correlated to assets.",
    joins=[(Asset, Asset.id == Vulnerability.asset_id)], link=("asset", Asset.id),
    default_columns=["severity", "cve_id", "title", "asset_name", "detected_on", "status"],
    default_sort="severity",
    fields=_fields(
        Field("cve_id", "CVE", "string", Vulnerability.cve_id),
        Field("title", "Title", "string", Vulnerability.title),
        Field("severity", "Severity", "enum", Vulnerability.severity, SEVERITIES),
        Field("cvss", "CVSS", "string", Vulnerability.cvss),
        Field("status", "Status", "enum", Vulnerability.status, ["open", "fixed", "accepted"]),
        Field("detected_on", "Detected", "date", Vulnerability.detected_on),
        Field("asset_tag", "Asset tag", "string", Asset.asset_tag),
        Field("asset_name", "Asset", "string", Asset.name),
        Field("asset_criticality", "Asset criticality", "enum", Asset.criticality, CRITICALITY),
        Field("department", "Department", "string", Asset.department),
    ),
))

_register(Entity(
    key="contracts", label="Contracts", base=Contract, category="Commercial", module="contracts",
    description="Leases, support, maintenance and subscriptions.",
    joins=[], default_columns=["name", "contract_type", "vendor", "end_date", "cost", "auto_renews"],
    default_sort="end_date",
    fields=_fields(
        Field("name", "Name", "string", Contract.name),
        Field("contract_type", "Type", "enum", Contract.contract_type, ["lease", "support", "maintenance", "subscription"]),
        Field("vendor", "Vendor", "string", Contract.vendor),
        Field("reference_no", "Reference", "string", Contract.reference_no),
        Field("start_date", "Start", "date", Contract.start_date),
        Field("end_date", "End", "date", Contract.end_date),
        Field("notice_days", "Notice (days)", "number", Contract.notice_days),
        Field("cost", "Cost", "number", Contract.cost),
        Field("currency", "Currency", "string", Contract.currency),
        Field("auto_renews", "Auto-renews", "bool", Contract.auto_renews),
    ),
))

_register(Entity(
    key="entitlements", label="Software licences", base=Entitlement, category="Commercial", module="entitlements",
    description="Purchased software entitlements (licence keys are never included).",
    joins=[], default_columns=["product", "vendor", "license_model", "seats_purchased", "expires_on"],
    default_sort="product",
    fields=_fields(
        Field("product", "Product", "string", Entitlement.product),
        Field("vendor", "Vendor", "string", Entitlement.vendor),
        Field("license_model", "Licence model", "string", Entitlement.license_model),
        Field("seats_purchased", "Seats", "number", Entitlement.seats_purchased),
        Field("expires_on", "Expires", "date", Entitlement.expires_on),
        Field("created_at", "Created", "datetime", Entitlement.created_at),
    ),
))


def catalog(enabled_modules: Optional[List[str]] = None) -> List[dict]:
    """Entities and fields for the report builder UI."""
    out = []
    for e in ENTITIES.values():
        out.append({
            "key": e.key, "label": e.label, "category": e.category, "description": e.description,
            "licensed": e.module is None or enabled_modules is None or e.module in enabled_modules,
            "default_columns": e.default_columns, "default_sort": e.default_sort,
            "link": e.link[0] if e.link else None,
            "fields": [{"key": f.key, "label": f.label, "type": f.type, "choices": f.choices,
                        "filter_only": f.filter_only} for f in e.fields.values()],
        })
    return out

