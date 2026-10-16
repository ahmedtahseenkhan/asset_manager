#!/usr/bin/env python3
"""
IT Asset Manager — inventory agent for macOS and Linux (schema v2).

Collects hardware, OS, software, updates, services, local accounts, security
posture (firewall, disk encryption, antivirus), disks, network adapters,
displays and printers, and reports them to the server. Standard library only;
Python 3.7+.

  python3 itam_agent.py --server http://itam.corp.local:8080 --token <agent-token>
  python3 itam_agent.py --dry-run          # print the report instead of sending it

--server/--token fall back to ITAM_SERVER / ITAM_TOKEN in the environment, so
schedulers can keep the token out of command lines (see install_agent.sh).
Run as root for complete data (serial numbers, account state, encryption).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

AGENT_VERSION = "2.1.0"


# ── helpers ─────────────────────────────────────────────────────────────────
def _run(cmd, timeout=60) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


def _json_cmd(cmd):
    out = _run(cmd)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def _section(fn, *args):
    """Run one collector. A collector that fails reports None ("not
    collected") so the server keeps what it had instead of wiping it."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — one bad section must not sink the report
        print(f"warning: {fn.__name__} failed: {exc}", file=sys.stderr)
        return None


def _gb(n_bytes) -> float | None:
    try:
        return round(float(n_bytes) / 1024 ** 3, 1)
    except (TypeError, ValueError):
        return None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _socket_ips() -> list:
    """Fallback when no interface tool is available."""
    try:
        return [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def _resolv_dns() -> list:
    return re.findall(r"^\s*nameserver\s+(\S+)", _read("/etc/resolv.conf"), re.M)


def _printers() -> list | None:
    if not _have("lpstat"):
        return None                       # no CUPS: not collected, rather than "no printers"
    if "is running" not in _run(["lpstat", "-r"]):
        return None                       # scheduler down: printer list unknown
    default = ""
    m = re.search(r"system default destination:\s*(\S+)", _run(["lpstat", "-d"]))
    if m:
        default = m.group(1)
    uris = dict(re.findall(r"^device for (\S+):\s*(\S+)", _run(["lpstat", "-v"]), re.M))
    names = re.findall(r"^printer (\S+)", _run(["lpstat", "-p"]), re.M)
    return [{
        "name": n, "port": uris.get(n),
        "is_network": bool(re.match(r"(ipps?|socket|lpd|dnssd|https?)://", uris.get(n, ""))),
        "is_default": n == default,
    } for n in names]


# ── macOS ───────────────────────────────────────────────────────────────────
def _plist_dicts(path: str) -> list:
    """Top-level array of dicts from a plist. Falls back to parsing plutil's
    XML when plistlib is unusable (e.g. a Python build with broken expat)."""
    try:
        import plistlib
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        xml = _run(["plutil", "-convert", "xml1", "-o", "-", path])
        out = []
        for block in re.findall(r"<dict>(.*?)</dict>", xml, re.S):
            d = {}
            # [^<]* keeps a key from swallowing a following <array> value
            for key, tag, val in re.findall(r"<key>([^<]*)</key>\s*<(string|date|integer)>([^<]*)</\2>", block):
                d[key] = datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ") if tag == "date" else val
            out.append(d)
        return out


def _mac_hardware(hw: dict) -> dict:
    procs = str(hw.get("number_processors", ""))
    m = re.match(r"proc (\d+)", procs)      # Apple silicon: "proc 10:4:6" = total:perf:eff
    cores = int(m.group(1)) if m else (int(procs) if procs.isdigit() else None)
    mem = re.match(r"([\d.]+)\s*GB", hw.get("physical_memory", ""))
    name = hw.get("machine_name") or ""
    total, _, _ = shutil.disk_usage("/")
    return {
        "manufacturer": "Apple",
        "model": f"{name} ({hw.get('machine_model')})" if hw.get("machine_model") else name or None,
        "serial_number": hw.get("serial_number"),
        "hardware_uuid": hw.get("platform_UUID"),
        "chassis_type": "laptop" if "Book" in name else "desktop",
        "is_virtual": _run(["sysctl", "-n", "kern.hv_vmm_present"]) == "1",
        "cpu": hw.get("chip_type") or hw.get("cpu_type"),
        "cpu_cores": cores or os.cpu_count(),
        "cpu_logical": os.cpu_count(),
        "ram_gb": float(mem.group(1)) if mem else None,
        "disk_gb": _gb(total),
        "bios_vendor": "Apple",
        "bios_version": hw.get("boot_rom_version"),
    }


def _mac_publisher(app: dict):
    """The signing identity names the publisher ("Developer ID Application:
    Google LLC (EQHXZ8M8AV)"); apps that ship with macOS are Apple's."""
    for signer in app.get("signed_by") or []:
        m = re.match(r"Developer ID Application: (.+?)(?: \([A-Z0-9]{10}\))?$", signer)
        if m:
            return m.group(1)
    return "Apple" if app.get("obtained_from") == "apple" else None


def _mac_software() -> list:
    data = _json_cmd(["/usr/sbin/system_profiler", "-json", "SPApplicationsDataType"]) or {}
    return [{"name": a.get("_name", ""), "version": a.get("version"), "publisher": _mac_publisher(a)}
            for a in data.get("SPApplicationsDataType", []) if a.get("_name")]


def _mac_updates() -> tuple:
    """(patches, newest XProtect update) from the install history."""
    patches, seen, xprotect = [], set(), None
    for e in _plist_dicts("/Library/Receipts/InstallHistory.plist"):
        if e.get("processName") != "softwareupdated":
            continue
        name = (e.get("displayName") or "").strip()
        pid = f"{name} {e.get('displayVersion') or ''}".strip()
        when = e.get("date")
        if "XProtect" in name and isinstance(when, datetime) and (xprotect is None or when > xprotect):
            xprotect = when
        if pid and pid not in seen:
            seen.add(pid)
            patches.append({"id": pid[:128], "description": name,
                            "installed_on": when.date().isoformat() if isinstance(when, datetime) else None})
    return patches, xprotect


def _mac_services() -> list:
    out = []
    for line in _run(["launchctl", "list"]).splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 3:
            out.append({"name": parts[2], "state": "running" if parts[0] != "-" else "stopped"})
    return out


def _mac_accounts() -> list:
    admins = set(re.sub(r"^GroupMembership:\s*", "", _run(["dscl", ".", "-read", "/Groups/admin", "GroupMembership"])).split())
    users = []
    for line in _run(["dscl", ".", "-list", "/Users", "UniqueID"]).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) >= 500 and not parts[0].startswith("_"):
            users.append(parts[0])
    accounts = []
    for u in users:
        auth = _run(["dscl", ".", "-read", f"/Users/{u}", "AuthenticationAuthority"])
        accounts.append({"name": u, "enabled": "DisabledUser" not in auth, "is_admin": u in admins})
    for a in sorted(admins - set(users)):
        if not a.startswith("_"):
            accounts.append({"name": a, "is_admin": True})
    return accounts


_KNOWN_AV = ("CrowdStrike", "Falcon", "SentinelOne", "Sophos", "Microsoft Defender", "Malwarebytes",
             "ESET", "Bitdefender", "Trend Micro", "McAfee", "Trellix", "Symantec", "Norton", "Kaspersky",
             "Cylance", "Carbon Black", "Avast", "Intego")


def _mac_security(software: list | None, xprotect: datetime | None) -> dict:
    fw = _run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"]).lower()
    fv = _run(["fdesetup", "status"])
    av = [{"name": "Apple XProtect", "enabled": True,
           # plist dates are naive UTC
           "up_to_date": (datetime.now(timezone.utc).replace(tzinfo=None) - xprotect) < timedelta(days=30)
           if xprotect else None,
           "definitions_date": xprotect.date().isoformat() if xprotect else None}]
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in _KNOWN_AV) + r")\b", re.I)
    for app in software or []:
        if pattern.search(app["name"]):
            av.append({"name": app["name"]})            # installed; running state unknown
    return {
        "antivirus": av,
        "firewall": [{"profile": "default", "enabled": "enabled" in fw}] if fw else None,
        "encryption": [{"volume": "/", "method": "FileVault", "protected": "FileVault is On" in fv,
                        "status": fv.splitlines()[0] if fv else None}] if fv else None,
    }


def _mac_nics() -> list:
    nics, cur = [], None
    for line in _run(["ifconfig"]).splitlines():
        m = re.match(r"^(\w+): flags", line)
        if m:
            cur = {"name": m.group(1), "ip_addresses": [], "active": False}
            nics.append(cur)
        elif cur is not None:
            s = line.strip()
            if s.startswith("ether "):
                cur["mac"] = s.split()[1].upper()
            elif s.startswith("inet "):
                cur["ip_addresses"].append(s.split()[1])
            elif s == "status: active":
                cur["active"] = True
    route = _run(["route", "-n", "get", "default"])
    gw = re.search(r"gateway:\s*(\S+)", route)
    gw_if = re.search(r"interface:\s*(\S+)", route)
    dns = _resolv_dns()
    out = []
    for n in nics:
        if n.get("mac") and n["ip_addresses"]:          # skips awdl0/llw0 and idle ports
            out.append({"name": n["name"], "mac": n["mac"], "ip_addresses": n["ip_addresses"],
                        "gateway": gw.group(1) if gw and gw_if and gw_if.group(1) == n["name"] else None,
                        "dns_servers": dns})
    return out


def _mac_monitors() -> list:
    data = _json_cmd(["/usr/sbin/system_profiler", "-json", "SPDisplaysDataType"]) or {}
    out = []
    for gpu in data.get("SPDisplaysDataType", []):
        for d in gpu.get("spdisplays_ndrvs", []):
            builtin = d.get("spdisplays_connection_type") == "spdisplays_internal"
            out.append({"manufacturer": "Apple" if builtin else None, "model": d.get("_name"),
                        "serial_number": d.get("_spdisplays_display-serial-number")})
    return out


def collect_macos(report: dict) -> None:
    data = _json_cmd(["/usr/sbin/system_profiler", "-json", "SPHardwareDataType"]) or {}
    hw = (data.get("SPHardwareDataType") or [{}])[0]
    report["hardware"] = _section(_mac_hardware, hw)
    report["os_name"] = "macOS"
    report["os_version"] = _run(["sw_vers", "-productVersion"]) or platform.mac_ver()[0]
    report["os_build"] = _run(["sw_vers", "-buildVersion"]) or None
    boot = re.search(r"sec = (\d+)", _run(["sysctl", "-n", "kern.boottime"]))
    report["last_boot"] = _iso(datetime.fromtimestamp(int(boot.group(1)), timezone.utc)) if boot else None
    report["logged_in_user"] = _run(["stat", "-f", "%Su", "/dev/console"]) or None
    report["software"] = _section(_mac_software)
    updates = _section(_mac_updates)
    report["patches"] = updates[0] if updates else None
    report["services"] = _section(_mac_services)
    report["local_accounts"] = _section(_mac_accounts)
    report["security"] = _section(_mac_security, report["software"], updates[1] if updates else None)
    total, _, free = shutil.disk_usage("/")
    report["disks"] = [{"name": "/", "filesystem": "apfs", "size_gb": _gb(total), "free_gb": _gb(free)}]
    report["network_adapters"] = _section(_mac_nics)
    report["monitors"] = _section(_mac_monitors)
    report["printers"] = _section(_printers)


# ── Linux ───────────────────────────────────────────────────────────────────
def _dmi(name: str) -> str | None:
    v = _read(f"/sys/class/dmi/id/{name}")
    return v or None


_CHASSIS = {"3": "desktop", "4": "desktop", "6": "desktop", "7": "desktop", "8": "laptop", "9": "laptop",
            "10": "laptop", "14": "laptop", "17": "server", "23": "server", "1": None}


def _linux_hardware() -> dict:
    cpuinfo = _read("/proc/cpuinfo")
    model = next(iter(re.findall(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)), None)
    if not model and _have("lscpu"):                  # ARM has no "model name" in cpuinfo
        m = re.search(r"^Model name:\s*(.+)$", _run(["lscpu"]), re.M)
        model = m.group(1).strip() if m and m.group(1).strip() not in ("-", "") else None
    phys = {(p, c) for p, c in re.findall(r"physical id\s*:\s*(\d+).*?core id\s*:\s*(\d+)", cpuinfo, re.S)}
    mem = re.search(r"MemTotal:\s*(\d+) kB", _read("/proc/meminfo"))
    virt = _run(["systemd-detect-virt"]) if _have("systemd-detect-virt") else ""
    product = _dmi("product_name") or ""
    board = " ".join(filter(None, [_dmi("board_vendor"), _dmi("board_name")])) or None
    return {
        "manufacturer": _dmi("sys_vendor"),
        "model": product or None,
        "serial_number": _dmi("product_serial"),       # root-only
        "hardware_uuid": _dmi("product_uuid"),         # root-only
        "chassis_type": _CHASSIS.get(_dmi("chassis_type") or ""),
        "is_virtual": (virt not in ("", "none")) or bool(re.search(r"VMware|VirtualBox|KVM|QEMU|Hyper-V", product)),
        "cpu": model,
        "cpu_cores": len(phys) or None,
        "cpu_logical": os.cpu_count(),
        "ram_gb": round(int(mem.group(1)) / 1024 ** 2, 1) if mem else None,
        "bios_vendor": _dmi("bios_vendor"),
        "bios_version": _dmi("bios_version"),
        "bios_date": _dmi("bios_date"),
        "motherboard": board,
    }


def _linux_software() -> list:
    if _have("dpkg-query"):
        out = _run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Maintainer}\n"])
    elif _have("rpm"):
        out = _run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\t%{VENDOR}\n"])
    else:
        return None
    sw = []
    for line in out.splitlines():
        name, _, rest = line.partition("\t")
        version, _, vendor = rest.partition("\t")
        if name:
            sw.append({"name": name, "version": version or None,
                       "publisher": vendor if vendor and vendor != "(none)" else None})
    return sw


def _linux_services() -> list | None:
    # systemctl can be installed without systemd running (containers): unknown, not "none".
    if not _have("systemctl") or not os.path.isdir("/run/systemd/system"):
        return None
    modes = dict(l.split()[:2] for l in _run(["systemctl", "list-unit-files", "--type=service", "--no-legend",
                                              "--no-pager"]).splitlines() if len(l.split()) >= 2)
    out = []
    for line in _run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--plain",
                      "--no-pager"]).splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service"):
            out.append({"name": parts[0], "display_name": parts[4] if len(parts) > 4 else None,
                        "state": parts[3], "start_mode": modes.get(parts[0])})
    return out


def _linux_accounts() -> list:
    groups = {}
    for line in _read("/etc/group").splitlines():
        parts = line.split(":")
        if len(parts) >= 4:
            groups[parts[0]] = set(filter(None, parts[3].split(",")))
    admins = {"root"} | groups.get("sudo", set()) | groups.get("wheel", set()) | groups.get("admin", set())
    shadow = {}
    for line in _read("/etc/shadow").splitlines():              # root-only; empty otherwise
        parts = line.split(":")
        if len(parts) > 1:
            shadow[parts[0]] = parts[1]
    accounts = []
    for line in _read("/etc/passwd").splitlines():
        parts = line.split(":")
        if len(parts) < 7:
            continue
        name, uid, shell = parts[0], int(parts[2]) if parts[2].isdigit() else -1, parts[6]
        if name != "root" and (uid < 1000 or uid == 65534):
            continue
        # Disabled = no login shell, or a locked password ("passwd -l" prefixes "!").
        # Without /etc/shadow (not root) the lock state is unknown.
        pw = shadow.get(name)
        if shell.endswith(("nologin", "false")):
            enabled = False
        elif pw is None:
            enabled = None
        else:
            enabled = not pw.startswith("!")
        accounts.append({"name": name, "enabled": enabled, "is_admin": name in admins})
    return accounts


def _linux_firewall() -> list | None:
    if _have("ufw"):
        out = _run(["ufw", "status"])
        if out:
            return [{"profile": "ufw", "enabled": "Status: active" in out}]
    if _have("firewall-cmd"):
        return [{"profile": "firewalld", "enabled": _run(["firewall-cmd", "--state"]) == "running"}]
    if _have("nft"):
        rules = _run(["nft", "list", "ruleset"])
        if rules:
            return [{"profile": "nftables", "enabled": "hook input" in rules}]
    return None


def _linux_encryption() -> list | None:
    data = _json_cmd(["lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINT"]) if _have("lsblk") else None
    if not data:
        return None
    out = []

    def walk(node, crypt=False):
        crypt = crypt or node.get("type") == "crypt"
        mp = node.get("mountpoint")
        if mp and os.path.isdir(mp) and not mp.startswith(("/boot", "/snap")):  # isdir: skip bind-mounted files
            out.append({"volume": mp, "method": "LUKS" if crypt else None, "protected": crypt})
        for child in node.get("children", []) or []:
            walk(child, crypt)

    for dev in data.get("blockdevices", []):
        walk(dev)
    return out


_LINUX_AV = {"falcon-sensor": "CrowdStrike Falcon", "sentinelone": "SentinelOne", "mdatp": "Microsoft Defender",
             "clamav-daemon": "ClamAV", "clamd": "ClamAV", "sophos-spl": "Sophos", "esets": "ESET",
             "cbagentd": "Carbon Black", "ds_agent": "Trend Micro Deep Security"}


def _linux_security(services: list | None) -> dict:
    av = None
    if services is not None:
        av = []
        for s in services:
            unit = s["name"][:-8] if s["name"].endswith(".service") else s["name"]
            if unit in _LINUX_AV:
                av.append({"name": _LINUX_AV[unit], "enabled": s.get("state") == "running"})
    sb = _run(["mokutil", "--sb-state"]) if _have("mokutil") else ""
    return {
        "antivirus": av,
        "firewall": _linux_firewall(),
        "encryption": _linux_encryption(),
        "tpm_present": os.path.exists("/sys/class/tpm/tpm0"),
        "secure_boot": ("enabled" in sb.lower()) if sb else None,
    }


def _linux_disks() -> list:
    out = []
    # Filesystem Type 1024-blocks Used Available Capacity Mounted-on
    for line in _run(["df", "-kPT", "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay"]).splitlines()[1:]:
        parts = line.split()
        if (len(parts) >= 7 and parts[0].startswith("/dev/") and os.path.isdir(parts[6])
                and not parts[6].startswith(("/boot", "/snap"))):
            out.append({"name": parts[6], "filesystem": parts[1],
                        "size_gb": _gb(int(parts[2]) * 1024), "free_gb": _gb(int(parts[4]) * 1024)})
    return out


def _linux_nics() -> list | None:
    data = _json_cmd(["ip", "-j", "addr"]) if _have("ip") else None
    if data is None:
        return None
    gw = re.search(r"default via (\S+) dev (\S+)", _run(["ip", "route", "show", "default"]))
    dns = _resolv_dns()
    out = []
    for n in data:
        name = n.get("ifname")
        ipv4 = [a["local"] for a in n.get("addr_info", []) if a.get("family") == "inet"]
        # Real Ethernet/Wi-Fi ports only: tunnels (tunl0, gre0, sit0…) report fake MACs.
        if n.get("link_type") != "ether" or not ipv4:
            continue
        speed = _read(f"/sys/class/net/{name}/speed")
        out.append({
            "name": name, "mac": (n.get("address") or "").upper() or None,
            "ip_addresses": ipv4,
            "speed_mbps": int(speed) if speed.lstrip("-").isdigit() and int(speed) > 0 else None,
            "dhcp": any(a.get("dynamic") for a in n.get("addr_info", [])),
            "gateway": gw.group(1) if gw and gw.group(2) == name else None,
            "dns_servers": dns,
        })
    return out


def collect_linux(report: dict) -> None:
    rel = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', _read("/etc/os-release"), re.M))
    report["hardware"] = _section(_linux_hardware)
    report["os_name"] = rel.get("NAME") or "Linux"
    report["os_version"] = rel.get("VERSION_ID") or platform.release()
    report["os_build"] = platform.release()                    # kernel
    up = _read("/proc/uptime").split()
    report["last_boot"] = _iso(datetime.now(timezone.utc) - timedelta(seconds=float(up[0]))) if up else None
    report["logged_in_user"] = (_run(["who"]).split() or [None])[0]
    report["pending_reboot"] = os.path.exists("/var/run/reboot-required") or None
    report["software"] = _section(_linux_software)
    report["services"] = _section(_linux_services)
    report["local_accounts"] = _section(_linux_accounts)
    report["security"] = _section(_linux_security, report["services"])
    report["disks"] = _section(_linux_disks)
    if report["hardware"] is not None and report["disks"]:
        report["hardware"]["disk_gb"] = round(sum(d["size_gb"] or 0 for d in report["disks"]), 1)
    report["network_adapters"] = _section(_linux_nics)
    report["printers"] = _section(_printers)


# ── report ──────────────────────────────────────────────────────────────────
def collect() -> dict:
    report = {
        "schema_version": 2,
        "collector_version": AGENT_VERSION,
        "hostname": socket.gethostname().split(".")[0],
        "fqdn": socket.getfqdn(),
        "architecture": platform.machine(),
    }
    if sys.platform == "darwin":
        collect_macos(report)
    elif sys.platform.startswith("linux"):
        collect_linux(report)
    else:
        report.update({"os_name": platform.system(), "os_version": platform.release()})

    nics = report.get("network_adapters") or []
    ips = {ip for n in nics for ip in n.get("ip_addresses", [])} or set(_socket_ips())
    report["ip_addresses"] = sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))
    report["mac_addresses"] = sorted({n["mac"] for n in nics if n.get("mac") and n["mac"] != "00:00:00:00:00:00"})
    return {k: v for k, v in report.items() if v is not None}


def main() -> None:
    ap = argparse.ArgumentParser(description="IT Asset Manager inventory agent")
    ap.add_argument("--server", default=os.environ.get("ITAM_SERVER"), help="e.g. http://itam.corp.local:8080")
    ap.add_argument("--token", default=os.environ.get("ITAM_TOKEN"))
    ap.add_argument("--dry-run", action="store_true", help="print the report as JSON; send nothing")
    ap.add_argument("--version", action="version", version=AGENT_VERSION)
    args = ap.parse_args()

    report = collect()
    if args.dry_run:
        print(json.dumps(report, indent=2, default=str))
        return
    if not args.server or not args.token:
        ap.error("--server and --token are required (or set ITAM_SERVER / ITAM_TOKEN)")

    req = urllib.request.Request(
        f"{args.server.rstrip('/')}/api/ingest/agent", data=json.dumps(report, default=str).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Agent-Token": args.token},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print("Reported OK:", r.read().decode())
    except Exception as exc:
        print(f"Report failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
