"""Feature modules a license can enable. Keep in sync with KNOWN_MODULES in
tools/license-signer/sign_license.py (the vendor tool is not shipped, so it
cannot import this)."""

ALL_MODULES = (
    "assets", "cmdb", "contracts", "entitlements", "notifications", "connectors",
    "discovery_plus",  # credentialed scanning: credential vault, scan targets, WinRM/WMI/SSH/SNMP
    "reporting",       # report builder, exports, scheduled reports
    "topology",        # network map (LLDP/CDP/switch ports)
    "cloud",           # virtualisation & cloud connectors
    "ot",              # OT / IoT discovery
)
