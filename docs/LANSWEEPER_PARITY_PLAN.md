# Lansweeper Parity — Implementation Plan

Goal: close the discovery and reporting gap with Lansweeper while keeping what
makes this product different (on-prem / air-gapped, SAM, contracts, CMDB,
licensing). Work proceeds phase by phase; each phase ends shippable.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Where we start (verified in code, 2026-10-15)

| Area | Today | Gap |
|---|---|---|
| Network discovery | Ping/ARP sweep + rDNS/NetBIOS/mDNS/SNMP(public)/SSDP/port probes | No credentials → no OS version, serial or software without an agent |
| Agent | Windows PS1 + macOS/Linux Python; hardware basics + software | No patches, services, users, AV, encryption, monitors, disks, NICs |
| Data model | `devices` + `device_sources.raw_data` JSON + `installed_software` | Software list is **deleted and re-inserted** on each report → no history |
| Scan config | One `connector_configs` row per connector (`connector_name` is unique) | Can't have several subnets/targets with different schedules or credentials |
| Credentials | Per-connector config only (encrypted) | No shared credential vault, no credential→target mapping |
| Reporting | 3 fixed reports + 2 CSV imports | No report builder, no exports, no scheduled reports |
| Topology / cloud / OT | — | Not present |

**Blockers found during the survey** (fixed in Phase 0):
1. **Migrations are stale.** Alembic covers only 5 tables (`users`, `devices`,
   `device_sources`, `connector_configs`, `sync_logs`). The real schema comes from
   `Base.metadata.create_all` at startup ([main.py](../backend/main.py)), which
   creates *new* tables but never *alters* existing ones. Any new column on
   `devices` or `assets` would silently not reach existing installs.
2. **The correlator doesn't know about the `agent` source.** `_FIELD_AUTHORITY`
   in [correlator.py](../backend/correlator/correlator.py) lists AD/EDR sources
   only, so agent data — the most accurate — has the lowest priority for OS fields.
3. **Test coverage is thin.** Only the correlator and normalizer have tests.

---

## Core design decision: one inventory pipeline

Every collector — agent, WinRM/WMI scan, SSH scan, SNMP scan, vCenter, cloud —
produces the **same `InventoryReport` payload** and goes through **one
`InventoryService.ingest(source, report)`**. That service:

1. resolves/creates the device via the correlator,
2. upserts each inventory section (hardware, software, patches, …),
3. diffs against the previous snapshot and writes **change history**,
4. pushes authoritative fields onto the linked asset.

This means the agent work in Phase 1 defines the data model once, and every
scanner after it is "just" a new way to fill the same payload. It also keeps
reports (Phase 3) simple: one set of tables regardless of how data was collected.

```
 agent ─┐
 WinRM ─┤                                  ┌─ devices / device_inventory
 WMI   ─┤   InventoryReport (v2 schema)    ├─ installed_software, patches, services,
 SSH   ─┼──────────────────────────────▶ ingest ─┤  local_accounts, disks, nics, monitors
 SNMP  ─┤        (one pipeline)            ├─ device_changes (history)
 vCenter┤                                  └─ assets (authoritative fields)
 cloud ─┘
```

---

## Phase 0 — Foundations

Must land first; everything after depends on it.

- [x] **0.1 Make Alembic authoritative.** Generate a catch-up migration for all
      current tables; stamp existing installs; run `alembic upgrade head` in the
      API container entrypoint and installer; keep `create_all` only for tests.
      *Done:* `0001_baseline` (squashed; the old revisions were never applied
      anywhere) + `0002_legacy_index_repair`; `backend/migrations.py` runs at
      startup under a Postgres advisory lock and adopts pre-Alembic installs;
      `tests/test_migrations.py` fails on any model change without a migration.
- [x] **0.2 `InventoryReport` v2 schema** (pydantic, versioned `schema_version`).
      Sections: `system`, `hardware`, `os`, `software`, `patches`, `services`,
      `local_accounts`, `security`, `disks`, `network_adapters`, `monitors`,
      `printers`. Every section optional so partial collectors work.
- [x] **0.3 `InventoryService`** generalising `AgentService.ingest` with a
      `source` parameter (`agent`, `winrm`, `wmi`, `ssh`, `snmp`, `vmware`, …).
      Agent endpoint keeps accepting the v1 payload (map → v2).
      *Done:* `schemas/inventory.py`, `services/inventory_service.py`. A `None`
      section means "not collected" and leaves stored data alone; software is
      diffed (rows kept, `last_seen` refreshed) instead of deleted and re-inserted.
- [x] **0.4 Correlator authority** — add `agent` (top) and the new scan sources to
      `_FIELD_AUTHORITY`; add serial number / machine UUID as match keys.
      *Done:* `devices.serial_number` / `hardware_uuid` (migration 0003);
      placeholder serials such as "To be filled by O.E.M." never match.
- [x] **0.5 Credential vault** — `scan_credentials` table (`EncryptedJSON`):
      types `windows`, `ssh_password`, `ssh_key`, `snmp_v2c`, `snmp_v3`,
      `vmware`, `cloud_*`. Admin-only CRUD, secrets never returned to the UI,
      "test credential" action, every change audited.
      *Done* except "test credential", which needs the protocol clients and
      moves to Phase 2 (2.9). `cloud_*` types arrive with Phase 5.
- [x] **0.6 Scan targets** — `scan_targets` table: type (CIDR, IP range, host
      list, AD OU), cron schedule, ordered credential list, enabled scan methods,
      concurrency. Scheduler registers one job per target (alongside connectors).
      *Done* for CIDR / range / host list; AD OU targets are 2.6. Also fixed:
      scheduled **connector** syncs had never registered (closures can't be
      stored by the persistent job store) and weren't registered at startup.
- [x] **0.7 Scan runs & per-host results** — `scan_runs` + `scan_host_results`
      (status, method used, credential used, error code/message, duration). This
      is Lansweeper's "scan queue / scan errors" view.
      *Done:* `scanning/runner.py` (background runs, one per target, cancel,
      runs interrupted by a restart are closed on startup); Scanning page with
      Targets / Credentials / History tabs.
- [x] **0.8 Licence modules** — add to `KNOWN_MODULES` and gate routers:
      `discovery_plus` (credentialed scanning), `reporting`, `topology`,
      `cloud`, `ot`. Dev licence re-issued with all modules.
- [x] **0.9 Test harness** — async API test client fixture (SQLite) + factories;
      every later phase adds tests for its ingest/collector/report code.

**Done when:** migrations upgrade a copy of the current dev DB cleanly; the agent
still reports end-to-end through `InventoryService`; credentials and targets
have API + UI pages; tests run in CI-style `pytest`.

---

## Phase 1 — Deep agent inventory + change history

Fastest visible win: no new network protocols, and it defines the data model
every later collector reuses.

**Data model** (new tables, all `device_id` FK, cascade delete)
- `device_inventory` (1:1): CPU model/cores, RAM, BIOS version/date, motherboard,
  uptime/last boot, pending reboot, TPM, Secure Boot, timezone, last logged-on user
- `device_patches`: KB/ID, description, installed_on
- `device_services`: name, display name, state, start mode, account
- `device_local_accounts`: name, enabled, last logon, **is_admin** (admin-group member)
- `device_security`: AV product(s) + status + definitions date, firewall per
  profile, disk encryption (BitLocker / FileVault / LUKS) per volume
- `device_disks` (volumes: size, free, filesystem), `device_network_adapters`
  (name, MAC, IPs, speed, DHCP, gateway, DNS), `device_monitors` (make, model,
  serial), `device_printers`
- `device_changes`: category, item, change type (added / removed / changed),
  old value, new value, source, detected_at

**Agents**
- [x] 1.1 Windows `itam_agent.ps1` v2 — `Win32_QuickFixEngineering`, `Get-Service`,
      `Get-LocalUser` + Administrators group, `SecurityCenter2\AntiVirusProduct`,
      `Get-NetFirewallProfile`, `Get-BitLockerVolume`, `Get-Tpm`,
      `Confirm-SecureBootUEFI`, `WmiMonitorID`, volumes, NICs, printers, uptime.
- [x] 1.2 macOS/Linux `itam_agent.py` v2 — `softwareupdate --history` / package
      history, `launchctl` / `systemctl`, `dscl` / `/etc/passwd` + sudo/admin
      groups, FileVault (`fdesetup`) / LUKS (`lsblk`), firewall (`socketfilterfw`
      / `ufw` / `firewalld`), disks, NICs. Stdlib only, as today.
- [x] 1.3 Agent reports its own `agent_version`; server shows outdated agents.
- [x] 1.4 Install helpers: Windows script that registers a Scheduled Task
      (SYSTEM, daily + at startup), Linux systemd timer, macOS launchd plist.
      Agents page shows copy-paste commands for each.

**Server**
- [x] 1.5 Section upserts in `InventoryService`; software is diffed instead of
      deleted/re-inserted.
- [x] 1.6 Change detection for: software installed/removed/upgraded, patch
      added, RAM/CPU/disk change, OS upgrade, new local admin, AV or encryption
      turned off. Retention for `device_changes` via the existing retention service.
- [x] 1.7 Notification rules on risky changes (new local admin, AV disabled,
      encryption off) using the existing SMTP/alert-rule plumbing.

**UI**
- [x] 1.8 Device detail tabs: Overview · Hardware · Software · Patches ·
      Services · Users · Security · Changes (timeline).
- [x] 1.9 Dashboard tiles: no AV, encryption off, pending reboot, local-admin
      sprawl, agents not reporting in 7 days.

**Done when:** a Windows and a macOS/Linux machine report full v2 inventory;
uninstalling an app or adding a local admin shows up in the Changes tab on the
next report.

*Status:* done. Verified end to end with the macOS agent on a real Mac and the
Linux agent in Debian/Ubuntu containers (Python 3.7 and 3.12). The Windows
agent is verified for syntax and report shape under PowerShell with stubbed
Windows cmdlets, **not yet on a real Windows machine** — first real-world run
should use `-DryRun`. The systemd unit files pass `systemd-analyze verify`;
the macOS LaunchDaemon install path has not been executed (it needs root on a
Mac). Linux patch history is not collected (left "not collected").

---

## Phase 2 — Credentialed agentless scanning (biggest gap)

Lansweeper's core: scan with credentials and get full inventory without an agent.

**Pipeline per scan target**
sweep (existing network_scan) → classify by open ports → try methods in order
with the target's credentials → map result to `InventoryReport` → `ingest`.
Remember the working credential per device to skip failed attempts next time.

| Port(s) found | Method | Library |
|---|---|---|
| 5985/5986 | **WinRM** — run the Phase 1 PowerShell collector remotely | `pypsrp` |
| 22 | **SSH** — pipe `itam_agent.py --dry-run` to `python3 -`; shell fallback if no Python | `asyncssh` |
| 161/udp | **SNMP v1/v2c/v3** — sysDescr/ObjectID, ENTITY-MIB serial/model, IF-MIB, Printer-MIB serial | `pysnmp` |

**Change from the original plan:** WMI over DCOM (via `impacket`) was dropped.
`impacket` is an offensive-security toolkit; shipping it in a customer-installed
product is a poor trade. Windows hosts are inventoried over WinRM, Microsoft's
supported remote-management protocol; hosts without WinRM get it via Group
Policy or run the agent. Printer toner levels were not added (serial only).

**Credential rules** (account-lockout safe): only credentials assigned to the
target, only against its addresses; at most 3 per method per host per run;
the last working credential first; stop at the first success. SSH host keys
are trusted on first use and checked *before* authenticating, so credentials
are never sent to a host whose key changed.

- [x] 2.1 Scan orchestrator: credentialed step after the sweep, bounded
      concurrency (max 16 sessions), per-host timeouts, results per host.
- [x] 2.2 WinRM collector — HTTPS 5986 when open, else HTTP 5985 with
      NTLM/Kerberos message encryption. **Not yet run against a real Windows host.**
- [x] ~~2.3 WMI/DCOM collector~~ — replaced by WinRM (see above).
- [x] 2.4 SSH collector (password or key, optional `sudo -n` for python3,
      basic report when python3 is missing). Verified against a real sshd.
- [x] 2.5 SNMP collector, v1/v2c/v3 with auth/priv, vendor from sysObjectID.
      Verified against a real snmpd (v2c and v3 AES).
- [x] 2.6 AD-driven targets: target type "Active Directory computers" (an OU
      or the connector's whole search base), resolved via DNS.
- [x] 2.7 Failed hosts show a code, a plain-language cause and the fix.
- [x] 2.9 "Test credential" — limited to hosts inside an enabled target that
      uses the credential.
- [x] 2.8 Admin guide: host preparation per method, ports, least privilege, Docker networking.

**Done when:** a Windows host with no agent shows the same tabs as an agent
host after a scan; a Linux host via SSH and a switch/printer via SNMPv3 also
populate; failed hosts show an actionable error.

*Status:* done for SSH and SNMP, verified end to end (scan → inventory →
device tabs) against real services in containers. WinRM is covered by unit
tests with a mocked client only; first use on a real Windows network should
start with **Test credential** on one host. Dependency note: `cryptography`
moved 42.0.5 → 50.0.2 (pysnmp needs ≥ 47 for SNMPv3 privacy; also fixes the
bundled-OpenSSL CVE-2024-12797).

---

## Phase 3 — Report builder, exports, scheduled reports

- [ ] 3.1 **Query compiler**: user picks an entity (assets, devices, software,
      patches, services, local accounts, security, vulnerabilities, changes,
      contracts, entitlements), columns, filters (`=, !=, contains, <, >, in,
      is empty, older than N days`), sort, group-by + count. Compiled to SQLAlchemy
      over a **whitelist of fields and predefined joins** — no raw SQL.
- [ ] 3.2 `saved_reports` table (owner, shared flag, definition JSON, chart type).
- [ ] 3.3 Built-in report library (~25), e.g.: devices without AV · encryption
      off · missing patch KB… · not seen in 30 days · local admins per device ·
      low disk space · software X installed · unlicensed software · EOL operating
      systems · warranty expiring in 90 days · changes in last 7 days.
- [ ] 3.4 Exports: CSV and XLSX (`openpyxl` already a dependency) for every
      report **and** every existing list page (assets, devices, software, …).
- [ ] 3.5 Scheduled reports: cron + recipients, emailed as XLSX via the existing
      SMTP relay.
- [ ] 3.6 UI: report builder page with live preview, table + optional chart,
      "pin to dashboard" widget.

**Done when:** a non-technical user can build "Windows laptops in Finance with
BitLocker off", save it, export to Excel, and get it emailed weekly.

---

## Phase 4 — Network topology map

- [ ] 4.1 SNMP topology collection from switches/routers: LLDP-MIB and CDP
      neighbours, BRIDGE-MIB / Q-BRIDGE forwarding tables (MAC → switch port),
      router ARP tables (`ipNetToMedia`).
- [ ] 4.2 Tables: `network_interfaces`, `network_links` (device/port ↔ device/port,
      source lldp/cdp/fdb), `mac_port_locations`.
- [ ] 4.3 "Where is this device plugged in?" on device detail (switch + port).
- [ ] 4.4 Map UI with `@xyflow/react`: auto-layout, filter by site/subnet/VLAN,
      node icons by device type, click → device. Same component renders the CMDB
      relationship graph for an asset.

**Done when:** scanning a managed switch draws its neighbours and shows which
port each discovered PC is on.

---

## Phase 5 — Virtualisation & cloud discovery

All implemented as connectors/collectors feeding `InventoryService`; VM↔host
links create CMDB `hosts` relationships automatically.

- [ ] 5.1 **VMware vCenter / ESXi** (vSphere REST via `httpx`; `pyvmomi` if REST
      lacks a field): clusters, hosts, VMs, datastores, power state, tools version.
- [ ] 5.2 **Hyper-V** via the Phase 2 WinRM collector (`Get-VM`, host ↔ VM).
- [ ] 5.3 **Microsoft Intune + Entra ID** via Microsoft Graph (`httpx`; reuses
      the Azure app-registration pattern from the Defender connector).
- [ ] 5.4 **AWS** (`boto3`: EC2, EBS, regions) and **Azure** (ARM REST via `httpx`):
      VMs and their tags/state. Optional — only useful where the server has
      internet access; clearly labelled as such for air-gapped customers.
- [ ] 5.5 `is_virtual` / `platform` (physical, vmware, hyperv, aws, azure) on
      devices; filters and reports by platform.

---

## Phase 6 — OT / IoT discovery (opt-in, read-only)

OT networks can be fragile; this phase is off by default and strictly read-only.

- [ ] 6.1 Separate OT scan targets with conservative defaults (low concurrency,
      rate limit, no port sweep beyond the protocol ports), and a UI warning to
      confirm before enabling.
- [ ] 6.2 Identification-only protocol probes: Modbus/TCP Read Device
      Identification (FC 43/14, port 502), BACnet/IP Who-Is/I-Am + device object
      (UDP 47808), EtherNet/IP ListIdentity (44818), Siemens S7 SZL identity (102).
- [ ] 6.3 OT device fields: vendor, product code, firmware, rack/slot, protocol;
      OT category in reports and the topology map.

---

## Phase 7 — Warranty & lifecycle enrichment

- [ ] 7.1 Bundled **OS / software end-of-life catalogue** (shipped with each
      release, works offline) → "EOL OS" flags and reports.
- [ ] 7.2 **Warranty lookup** for Dell / Lenovo / HP by serial — optional, needs
      internet + vendor API keys; offline alternative: warranty CSV import.
      Fills `warranty_end`, which already drives the lifecycle forecast report.
- [ ] 7.3 Software catalogue: publisher/category normalisation to improve SAM
      matching and the "unwanted software" report.

---

## Cross-cutting rules (apply to every phase)

- **Security:** credentials only in `EncryptedJSON`, admin-only, never logged or
  returned; every scan/credential/report action in the hash-chained audit log.
- **Licensing:** each phase's routers gated with `require_module(...)`.
- **Migrations:** every schema change ships an Alembic migration (after 0.1).
- **Tests:** collectors tested against recorded fixtures (sample WMI/SNMP/SSH
  outputs), ingest + change detection tested on SQLite, report compiler tested
  for field whitelisting.
- **Air-gapped:** new Python deps vendored as wheels in the offline bundle;
  no feature may require internet unless labelled optional (5.4, 7.2).
- **Docs:** update `OPERATIONS.md` / `ADMIN_GUIDE.md` at the end of each phase.

---

## Order and relative size

| # | Phase | Size | Depends on |
|---|---|---|---|
| 0 | Foundations | M | — |
| 1 | Deep agent inventory + change history | L | 0 |
| 2 | Credentialed scanning (WinRM, WMI, SSH, SNMP) | XL | 0, 1 |
| 3 | Report builder + exports + scheduled reports | L | 1 (richer once 2 lands) |
| 4 | Topology map | L | 2 (SNMP collector) |
| 5 | Virtualisation & cloud | M–L | 0; Hyper-V needs 2 |
| 6 | OT / IoT | M | 0 |
| 7 | Warranty & lifecycle | S–M | 1 |

Phases 5–7 are independent of each other and can be reordered by customer demand.

---

## Decisions to confirm before starting

1. **Windows scanning order** — recommended: WinRM first (simpler, encrypted,
   reuses the agent script), WMI/DCOM second (needed for workstations).
2. **Cloud connectors (5.4)** — keep in scope even though the product is
   positioned as air-gapped? Recommended: yes, but optional and last.
3. **Raw SQL reports** — recommended: **no**; the whitelisted builder covers
   Lansweeper-style needs without giving users a way to read secrets or hashes.
4. **Licence packaging** — the module names in 0.8 decide what can be sold
   separately; adjust before the dev licence is re-issued.
