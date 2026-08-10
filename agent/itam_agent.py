#!/usr/bin/env python3
"""
IT Asset Manager — cross-platform inventory agent (macOS / Linux).

Collects real OS/hardware/software detail and reports it to the server.
Uses only the Python standard library — no dependencies.

  python3 itam_agent.py --server http://itam.corp.local:8000 --token <agent-token>

Schedule daily via cron/launchd for continuous inventory.
"""
import argparse
import json
import platform
import socket
import subprocess
import sys
import urllib.request


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _ips() -> list[str]:
    out = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                out.add(ip)
    except Exception:
        pass
    return sorted(out)


def _macos_inventory() -> dict:
    serial = _run(["ioreg", "-l"])  # fallback below is cleaner
    serial = _run(["/usr/sbin/system_profiler", "SPHardwareDataType"])
    fields = {}
    for line in serial.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    # Installed apps
    apps_raw = _run(["/usr/sbin/system_profiler", "-json", "SPApplicationsDataType"])
    software = []
    try:
        for a in json.loads(apps_raw).get("SPApplicationsDataType", []):
            software.append({"name": a.get("_name", ""), "version": a.get("version", ""),
                             "publisher": a.get("obtained_from", "")})
    except Exception:
        pass
    mem = fields.get("Memory", "")
    ram_gb = None
    if "GB" in mem:
        try:
            ram_gb = float(mem.split()[0])
        except Exception:
            pass
    return {
        "os_name": "macOS",
        "os_version": f"{platform.mac_ver()[0]}".strip(),
        "serial_number": fields.get("Serial Number (system)"),
        "manufacturer": "Apple",
        "model": fields.get("Model Name") or fields.get("Model Identifier"),
        "cpu": fields.get("Chip") or fields.get("Processor Name"),
        "ram_gb": ram_gb,
        "logged_in_user": _run(["/usr/bin/stat", "-f", "%Su", "/dev/console"]) or None,
        "software": software,
    }


def _linux_inventory() -> dict:
    def cat(path: str) -> str:
        try:
            return open(path).read().strip()
        except Exception:
            return ""
    # dpkg / rpm software list
    software = []
    dpkg = _run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"])
    if dpkg:
        for line in dpkg.splitlines():
            name, _, ver = line.partition("\t")
            software.append({"name": name, "version": ver, "publisher": ""})
    else:
        rpm = _run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}\n"])
        for line in rpm.splitlines():
            name, _, ver = line.partition("\t")
            software.append({"name": name, "version": ver, "publisher": ""})
    pretty = ""
    for line in cat("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty = line.split("=", 1)[1].strip().strip('"')
    return {
        "os_name": "Linux",
        "os_version": pretty or platform.release(),
        "serial_number": cat("/sys/class/dmi/id/product_serial") or None,
        "manufacturer": cat("/sys/class/dmi/id/sys_vendor") or None,
        "model": cat("/sys/class/dmi/id/product_name") or None,
        "cpu": next((l.split(":", 1)[1].strip() for l in cat("/proc/cpuinfo").splitlines()
                     if l.startswith("model name")), None),
        "logged_in_user": _run(["/usr/bin/whoami"]) or None,
        "software": software,
    }


def collect() -> dict:
    base = {
        "hostname": socket.gethostname().split(".")[0],
        "fqdn": socket.getfqdn(),
        "ip_addresses": _ips(),
        "mac_addresses": [],
        "software": [],
    }
    if sys.platform == "darwin":
        base.update(_macos_inventory())
    elif sys.platform.startswith("linux"):
        base.update(_linux_inventory())
    else:
        base.update({"os_name": platform.system(), "os_version": platform.release()})
    return base


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="e.g. http://itam.corp.local:8000")
    ap.add_argument("--token", required=True)
    args = ap.parse_args()

    payload = json.dumps(collect()).encode()
    req = urllib.request.Request(
        f"{args.server}/api/ingest/agent", data=payload, method="POST",
        headers={"Content-Type": "application/json", "X-Agent-Token": args.token},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("Reported OK:", r.read().decode())
    except Exception as exc:
        print(f"Report failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
