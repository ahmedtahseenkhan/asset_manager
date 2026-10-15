# Operations Guide — Discovery, SAM, Posture & Reporting

This covers the day-to-day workflows added on top of the core asset register:
agent rollout, software licensing, security posture, CMDB health, and reporting.
For install/licensing/backup basics see [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

---

## 0. Network scanning (Scanning page)

**Scanning** (admin only, licence module `discovery_plus`) replaces the single
Network Scan connector with any number of **scan targets**:

- **Scan targets** — a name, the addresses (subnet `192.168.1.0/24`, range
  `10.0.0.10-10.0.0.50`, or a host list `srv01, srv02.corp.local`), optional
  exclusions, and a schedule (manual, daily, every 6 h, weekly, or cron).
  *Check addresses* shows how many IPs a target covers before you save it
  (limit 4,096 per target). **Run now** starts a scan immediately.
- **Credentials** — accounts for credentialed scanning (Windows, SSH password
  or key, SNMP v1/v2c/v3, VMware). Secrets are encrypted and never shown again.
  Attach credentials to a target in the order they should be tried.
  *Credentialed scanning itself (WinRM, WMI, SSH, SNMP inventory) is not
  released yet; until then every run is a network sweep.*
- **Scan history** — every run with its status, duration, how many addresses
  responded, and per-host results linking to the discovered device.

Only one run per target executes at a time; a scheduled run is skipped if the
previous one is still going. Runs interrupted by a server restart are marked
failed with that reason.

> In Docker, the API container sits on Docker's internal network: pings reach
> your LAN, but MAC addresses and some name lookups won't. Enter real subnets —
> never rely on auto-detection inside a container.

---

## 1. Agent rollout (the deepest, most reliable inventory)

A network scan sees *presence*; the **agent** sees *identity and state*. It
reports **outbound** to the server, so it works through firewalls, behind
client-isolated Wi-Fi, and for off-network laptops.

**What agent 2.0 collects** — hardware (make, model, serial, CPU, RAM, BIOS),
OS with build/patch level, installed software, installed updates (Windows
hotfixes; macOS software updates), services, local accounts and who is in the
Administrators group, antivirus status, firewall, disk encryption (BitLocker /
FileVault / LUKS), TPM and Secure Boot, disks, network adapters, monitors,
printers, last boot, pending reboot. Each part is collected independently: if
one fails (e.g. no admin rights for BitLocker), the rest still reports and the
server keeps the last known value for the part that failed.

### Step 1 — create an enrollment token
**Agents → Enrollment tokens → Create** (label it, e.g. `laptops-2026`). Copy
the token immediately; it is shown once. Disable/rotate tokens any time.

### Step 2 — install the agent
The Agents page shows ready-to-paste commands with your server URL and token
filled in. The installers set up a **daily report plus one shortly after
boot**, and send the first report immediately.

- **Windows** (elevated PowerShell) — installs to `%ProgramData%\ITAM`
  (readable only by SYSTEM and Administrators) and registers the scheduled task
  *ITAM Inventory Agent*, running as SYSTEM:
  ```
  iwr -UseBasicParsing "http://<server>/api/agents/download/install_agent.ps1" -OutFile install_agent.ps1
  powershell -ExecutionPolicy Bypass -File .\install_agent.ps1 -Server "http://<server>" -Token "<token>"
  ```
- **macOS / Linux** (needs sudo; Python 3.7+, stdlib only) — Linux uses a
  systemd timer (cron where systemd is absent), macOS a LaunchDaemon. The token
  is kept in a root-only file (`/etc/itam/agent.env`, `/Library/ITAM/agent.env`):
  ```
  curl -fsSL http://<server>/api/agents/download/install_agent.sh | sudo sh -s -- --server http://<server> --token <token>
  ```
- **GPO / Intune / MDM** — deploy `install_agent.*` together with
  `itam_agent.*` (download links under *Run once without installing*); the
  installer uses the agent file found next to it.
- **Uninstall** — `install_agent.ps1 -Uninstall` / `install_agent.sh --uninstall`.
- **Check what an agent would send** — `itam_agent.ps1 -DryRun` /
  `itam_agent.py --dry-run` prints the report without sending it.

The **Reporting devices** list on the Agents page shows every agent's version
and last report; agents older than the current version are marked *update*
(reinstall to update), and reports older than 7 days are highlighted.

### What the agent does to your data
- Creates/updates the device (source `agent`) — merged with the same machine
  seen by scans or other connectors on hardware UUID, serial number or name.
- Fills the device page tabs: Hardware, Software, Updates, Services, Users,
  Security, Changes.
- **Pushes real serial / model / OS / IP / MAC onto the linked asset.**

### Change history and alerts
From the second report onwards, differences are recorded on the device's
**Changes** tab: software installed / removed / updated, updates installed,
hardware and OS changes, new or changed local accounts, services added or
removed. The first report is a baseline and records nothing.

Risky changes are flagged in red and listed on the dashboard: **a new local
admin, an account becoming admin, antivirus removed or disabled, firewall
turned off, disk encryption turned off**. Enable **Notifications → Risky device
changes** to get a daily email of them; each change is emailed once. History is
kept for 365 days.

### Endpoint health
The dashboard's **Endpoint health** panel counts devices with no working
antivirus, firewall off, unencrypted disks, 3+ local admins, a pending reboot,
or no inventory for 7+ days. Each tile opens the matching device list.

---

## 2. Software & Licensing (SAM)

**Software** page. Two parts:

- **License Position** — every entitlement reconciled against *actual installs*
  discovered by the agent (matched on normalized product name):
  - `compliant` — consumption equals purchased seats
  - `over-deployed` — more installs than seats (the **Gap** column shows the
    true-up shortfall; the summary totals it)
  - `under-utilized` — spare seats you're paying for
- **Discovered Software** — every product found across the fleet with an install
  count. Use it to spot unlicensed or unwanted software.

**Workflow:** add entitlements under **Entitlements** with a `product` name that
matches what's installed (e.g. "Microsoft 365", "Zoom"), deploy agents, then read
the position. Over-deployed rows are your audit/true-up risk.

---

## 3. Security Posture (CAASM)

**Security Posture** page — the cyber-asset attack-surface view.

- **Control coverage rings** — % of assets that have an agent, are onboarded as a
  log source, are data-classified, have been vuln-scanned, and are monitored.
  These start low and climb as you deploy agents and classify assets.
- **Open vulnerabilities** — counts by severity + severity-weighted **top-risk
  assets** (critical×40, high×10, medium×3, low×1).
- **Log-source coverage** — deployed assets *not* onboarded to your SIEM (your
  control gaps), critical/high first.
- **CMDB health** — device/asset totals, managed %, unmanaged, duplicate
  hostnames, stale assets.

### Importing vulnerabilities
**Security Posture → Import vulnerabilities (CSV)**. Export from your scanner
(Nessus, Qualys, OpenVAS, Defender) and map columns to:

```
cve,title,severity,cvss,ip,detected_on
CVE-2024-1234,OpenSSL buffer overflow,critical,9.8,192.168.100.194,2026-08-01
```

Findings correlate to an asset by `asset_tag` or `ip`. Matched assets get their
`last_vulnerability_scan` date updated automatically; unmatched findings are
counted and reported. Per-asset findings appear on the asset detail page.

---

## 4. Reports

**Reports** page:
- **Capital by category / department** — total spend from `purchase_cost`.
- **Lifecycle forecast (12 mo)** — warranties and EOL/EOS dates expired or coming
  due, with the upcoming list. Drives refresh planning.
- **Compliance & governance** — criticality and data-classification distribution,
  and the % of assets with an owner and a review date.

Fill in `purchase_cost`, `warranty_end`, `eol_eos_date`, and the governance
fields (via the asset form or **bulk edit**) to make these meaningful.

---

## 5. Bulk operations & CSV import

- **Bulk edit** (`POST /api/assets/bulk-update`) — set security/governance fields
  (criticality, data classification, log-source status, monitoring, backup,
  owner, department, …) across many assets at once. Ideal for classifying a
  freshly-discovered batch.
- **CSV asset import** (`POST /api/assets/import`) — create assets in bulk.
  Required column `name`; optional `category, asset_type, serial_number, vendor,
  model, ip_address, os_name, criticality, department, …`. Auto-assigns tags.

---

## Recommended onboarding order

1. **Scan** your real LAN (Scanning → Scan targets) to find what's there.
2. **Adopt** the devices you manage (Assets → Reconcile).
3. **Deploy agents** (Agents page installers) → hardware, software, patches and security posture auto-populate.
4. **Classify** in bulk — set criticality, data classification, owner.
5. **Onboard log sources** and mark `log_source_status` → posture coverage rises.
6. **Import vulnerabilities** regularly → risk ranking stays current.
7. **Add entitlements** → the license position becomes live.
8. **Review Reports & Posture** monthly; run the CMDB audit to catch drift.
