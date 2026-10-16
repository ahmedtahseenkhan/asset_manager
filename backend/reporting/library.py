"""
Built-in reports. Each is an ordinary report definition, so users can open
one in the builder, adjust it, and save their own copy. Ids are stable
("builtin:<slug>") so bookmarks and pins keep working across releases.
"""
from __future__ import annotations

from typing import Dict, List


def _r(slug, category, title, description, entity, *, columns=None, filters=(), match="all",
       group_by=None, sort=None, sort_dir="asc", chart="none") -> dict:
    return {
        "id": f"builtin:{slug}", "category": category, "name": title, "description": description,
        "definition": {
            "entity": entity, "columns": list(columns or []),
            "filters": [{"field": f, "op": op, "value": v} for f, op, v in filters],
            "match": match, "group_by": group_by, "sort": sort, "sort_dir": sort_dir, "chart": chart,
        },
    }


_DEVICE_COLS = ["hostname", "os_name", "manufacturer", "model", "logged_in_user", "collected_at"]

LIBRARY: List[dict] = [
    # ── Endpoint security ──
    _r("no-antivirus", "Endpoint security", "Devices without working antivirus",
       "No antivirus product, or every product disabled or out of date.", "devices",
       columns=_DEVICE_COLS, filters=[("antivirus_ok", "is_false", None)]),
    _r("firewall-off", "Endpoint security", "Devices with the firewall off",
       "At least one firewall profile is turned off.", "devices",
       columns=_DEVICE_COLS, filters=[("firewall_ok", "is_false", None)]),
    _r("not-encrypted", "Endpoint security", "Devices with unencrypted disks",
       "A fixed disk without BitLocker / FileVault / LUKS protection.", "devices",
       columns=_DEVICE_COLS + ["chassis_type"], filters=[("disk_encrypted", "is_false", None)]),
    _r("admin-sprawl", "Endpoint security", "Devices with 3 or more local admins",
       "Members of the local Administrators group, including domain groups.", "devices",
       columns=["hostname", "os_name", "local_admin_count", "logged_in_user"],
       filters=[("local_admin_count", "gte", 3)], sort="local_admin_count", sort_dir="desc"),
    _r("local-admins", "Endpoint security", "Local administrator accounts",
       "Every account with admin rights, per device.", "local_accounts",
       columns=["hostname", "name", "enabled", "last_logon"], filters=[("is_admin", "is_true", None)],
       sort="hostname"),
    _r("remote-access-tools", "Endpoint security", "Remote-access tools installed",
       "TeamViewer, AnyDesk and similar tools, which are often unapproved.", "software",
       columns=["hostname", "name", "version", "publisher"], match="any",
       filters=[("name", "contains", n) for n in ("TeamViewer", "AnyDesk", "RustDesk", "VNC", "LogMeIn",
                                                  "ScreenConnect", "Splashtop")], sort="name"),
    _r("risky-changes", "Endpoint security", "Risky changes in the last 7 days",
       "New local admins, antivirus, firewall or encryption turned off.", "changes",
       filters=[("severity", "eq", "warning"), ("detected_at", "within_last_days", 7)],
       sort="detected_at", sort_dir="desc"),
    _r("defender-signatures", "Endpoint security", "Antivirus definitions out of date",
       "Products whose definitions are not current.", "antivirus",
       columns=["hostname", "name", "enabled", "definitions_date"], filters=[("up_to_date", "is_false", None)]),

    # ── Updates ──
    _r("updates-30d", "Updates", "Updates installed in the last 30 days",
       "Hotfixes and software updates recorded by agents and scans.", "patches",
       filters=[("installed_on", "within_last_days", 30)], sort="installed_on", sort_dir="desc"),
    _r("missing-kb", "Updates", "Windows devices missing a specific update",
       "Edit the update ID (e.g. KB5034441) to check any patch.", "devices",
       columns=["hostname", "os_name", "os_build", "collected_at"],
       filters=[("os_name", "contains", "Windows"), ("has_patch", "has_not", "KB5034441")]),
    _r("windows-builds", "Updates", "Windows devices by OS build",
       "Shows how far each build is on the cumulative-update track.", "devices",
       filters=[("os_name", "contains", "Windows")], group_by="os_build", chart="bar"),
    _r("reboot-pending", "Updates", "Devices waiting for a reboot",
       "Updates or software changes that need a restart to finish.", "devices",
       columns=["hostname", "os_name", "last_boot", "logged_in_user"], filters=[("pending_reboot", "is_true", None)]),

    # ── Software ──
    _r("software-by-installs", "Software", "Software by number of installs",
       "Every application across the fleet, most installed first.", "software",
       group_by="name", chart="bar"),
    _r("new-software-7d", "Software", "Software installed in the last 7 days",
       "Applications that appeared on devices this week.", "changes",
       columns=["detected_at", "hostname", "item", "new_value"],
       filters=[("category", "eq", "software"), ("change_type", "eq", "added"),
                ("detected_at", "within_last_days", 7)], sort="detected_at", sort_dir="desc"),
    _r("no-chrome", "Software", "Devices without Google Chrome",
       "Edit the application name to check coverage of any software.", "devices",
       columns=["hostname", "os_name", "logged_in_user"],
       filters=[("inventory_source", "is_not_empty", None), ("has_software", "has_not", "Google Chrome")]),

    # ── Hardware & lifecycle ──
    _r("os-distribution", "Hardware", "Devices by operating system",
       "Operating systems reported by agents and scans.", "devices",
       filters=[("os_name", "is_not_empty", None)], group_by="os_name", chart="pie"),
    _r("models", "Hardware", "Devices by model", "Hardware models in the fleet.", "devices",
       filters=[("model", "is_not_empty", None)], group_by="model", chart="bar"),
    _r("low-ram", "Hardware", "Devices with less than 8 GB RAM",
       "Candidates for upgrade or replacement.", "devices",
       columns=["hostname", "model", "ram_gb", "cpu", "logged_in_user"], filters=[("ram_gb", "lt", 8)],
       sort="ram_gb"),
    _r("low-disk", "Hardware", "Disks with less than 10% free",
       "Volumes close to full.", "volumes",
       columns=["hostname", "name", "size_gb", "free_gb", "free_pct"], filters=[("free_pct", "lt", 10)],
       sort="free_pct"),
    _r("virtual-machines", "Hardware", "Virtual machines", "Devices reporting a virtual platform.", "devices",
       columns=["hostname", "os_name", "model", "cpu_cores", "ram_gb"], filters=[("is_virtual", "is_true", None)]),
    _r("monitors", "Hardware", "Monitor inventory", "Displays attached to devices, with serials.", "monitors"),
    _r("not-seen-30d", "Hardware", "Devices not seen in 30 days",
       "Possibly lost, retired or offline for long periods.", "devices",
       columns=["hostname", "os_family", "last_seen", "status"], filters=[("last_seen", "older_than_days", 30)],
       sort="last_seen"),
    _r("stale-inventory", "Hardware", "No inventory for 7+ days",
       "The agent stopped reporting or the scan can't reach the device.", "devices",
       columns=["hostname", "inventory_source", "collector_version", "collected_at"],
       filters=[("collected_at", "older_than_days", 7)], sort="collected_at"),

    # ── Assets & commercial ──
    _r("warranty-90d", "Assets & contracts", "Warranties ending in the next 90 days",
       "Plan renewals or replacements.", "assets",
       columns=["asset_tag", "name", "model", "department", "warranty_end"],
       filters=[("warranty_end", "within_next_days", 90)], sort="warranty_end"),
    _r("past-eol", "Assets & contracts", "Assets past end of life",
       "Unsupported hardware or software still in the register.", "assets",
       columns=["asset_tag", "name", "model", "eol_eos_date", "lifecycle_state"],
       filters=[("eol_eos_date", "is_past", None), ("lifecycle_state", "neq", "retired")], sort="eol_eos_date"),
    _r("no-owner", "Assets & contracts", "Assets without an owner",
       "No owner/contact recorded.", "assets",
       columns=["asset_tag", "name", "department", "lifecycle_state"],
       filters=[("point_of_contact", "is_empty", None), ("lifecycle_state", "neq", "retired")]),
    _r("assets-by-dept", "Assets & contracts", "Assets by department", "Headcount of assets per department.",
       "assets", group_by="department", chart="bar"),
    _r("critical-unmonitored", "Assets & contracts", "Critical assets not monitored",
       "Critical assets without active monitoring.", "assets",
       columns=["asset_tag", "name", "monitoring_status", "log_source_status", "point_of_contact"],
       filters=[("criticality", "eq", "critical"), ("monitoring_status", "neq", "monitored")]),
    _r("contracts-60d", "Assets & contracts", "Contracts ending in the next 60 days",
       "Renewals coming up.", "contracts", filters=[("end_date", "within_next_days", 60)], sort="end_date"),
    _r("licences-90d", "Assets & contracts", "Software licences expiring in the next 90 days",
       "Entitlements to renew.", "entitlements", filters=[("expires_on", "within_next_days", 90)],
       sort="expires_on"),
    _r("open-critical-vulns", "Assets & contracts", "Open critical and high vulnerabilities",
       "Imported findings still open.", "vulnerabilities",
       filters=[("severity", "in", "critical,high"), ("status", "eq", "open")], sort="severity"),
]

BY_ID: Dict[str, dict] = {r["id"]: r for r in LIBRARY}
