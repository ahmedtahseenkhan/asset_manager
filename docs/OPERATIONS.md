# Operations Guide — Discovery, SAM, Posture & Reporting

This covers the day-to-day workflows added on top of the core asset register:
agent rollout, software licensing, security posture, CMDB health, and reporting.
For install/licensing/backup basics see [ADMIN_GUIDE.md](ADMIN_GUIDE.md).

---

## 0. Network scanning (Scanning page)

**Scanning** (admin only, licence module `discovery_plus`) replaces the single
Network Scan connector with any number of **scan targets**:

- **Scan targets** — a name, the addresses (subnet `192.168.1.0/24`, range
  `10.0.0.10-10.0.0.50`, a host list `srv01, srv02.corp.local`, or *Active
  Directory computers* — an OU such as `OU=Workstations,DC=corp,DC=local`, or
  `*` for the AD connector's whole search base), optional exclusions, and a
  schedule (manual, daily, every 6 h, weekly, or cron). *Check addresses* shows
  how many IPs a target covers before you save it (limit 4,096 per target).
  **Run now** starts a scan immediately.
- **Credentialed scanning** — tick **WinRM** (Windows), **SSH** (Linux, macOS,
  Unix) and/or **SNMP** (switches, routers, printers) on a target and attach
  credentials in the order they should be tried. After the sweep, every
  responding host is inventoried with them and gets the same device tabs as an
  agent host (hardware, software, updates, services, users, security, changes).
  Host preparation per method: [ADMIN_GUIDE.md §8a](ADMIN_GUIDE.md).
- **Credentials** — Windows, SSH password or key, SNMP v1/v2c/v3, VMware.
  Secrets are encrypted and never shown again. **Test** (plug icon) signs in to
  one host inside one of the credential's targets and reports exactly what
  works or fails. *Trusted SSH host keys* lists the keys remembered per host.
- **Scan history** — every run with its status, duration, how many addresses
  responded and how many were inventoried or failed. Each host shows the method
  and credential used and, when it failed, the cause and how to fix it.

Only one run per target executes at a time; a scheduled run is skipped if the
previous one is still going. Runs interrupted by a server restart are marked
failed with that reason.

> In Docker, the API container sits on Docker's internal network: pings and
> credentialed scans reach your LAN, but MAC addresses and some name lookups
> won't. Enter real subnets — never rely on auto-detection inside a container.

**Agent or credentialed scan?** Both produce the same inventory. Use the agent
for laptops and machines that leave the network; use credentialed scans for
servers and network devices you can reach and where installing software is
unwelcome. A machine reached both ways is merged into one device.

**Testing collectors (developers).** `backend/tests/live/compose.yml` starts an
SSH server and an SNMP agent on localhost; then run
`ITAM_LIVE_TESTS=1 ./.venv/bin/python -m pytest tests/test_collectors_live.py`
from `backend/`.

---

## 0b. Network map

**Network map** (licence module `topology`) draws switches, routers and the
links between them, and shows which switch port every device is plugged into.

- Data comes from SNMP: when a scan target with **SNMP** ticked inventories a
  switch or router, its LLDP/CDP neighbours, MAC address table and ARP cache
  are read too. Neighbours that haven't been scanned yet appear dashed.
- **Show connected devices** adds the devices on each access port; filter by
  VLAN for large networks (the map shows up to 500 devices).
- Click a switch for its port table (status, VLAN, neighbour, what's plugged
  in); click a device to see its port. Every device page also has a **Network
  location** card ("Plugged into ACCESS-SW port Gi1/0/12 · VLAN 20"), and
  switches/routers get a **Ports** tab.
- Devices found by a scan from inside Docker have no MAC address; they are
  located through the routers' ARP tables, so include your routers / layer-3
  switches in the SNMP target.

## 0c. Virtual machines (Hyper-V)

Hyper-V hosts report their guests automatically: install the agent on the host,
or include the host in a scan target with **WinRM** ticked. Nothing extra to
configure. Collection runs only where the Hyper-V PowerShell module is present,
so ordinary PCs are unaffected.

- Every guest becomes a device of type **Virtual machine**, with its host,
  power state (running / off / suspended), vCPUs, memory, disk size,
  integration services state and, for running guests with integration
  services, its IP addresses, FQDN and OS name.
- A host's device page has a **Virtual machines** tab (with totals for running
  guests); a guest's page shows which host it runs on.
- A guest that also runs the agent, or is scanned, stays **one device**: it is
  matched by its BIOS UUID. The guest's own inventory always wins; the host
  only fills in what the guest hasn't reported. Guests known only from their
  host say so on their page. **Reports → Library → Virtual machines without
  their own inventory** lists them, so you can close the gap.
- Live migration moves the guest to its new host on the next report from
  either host. A guest deleted from Hyper-V leaves the host's list on the
  host's next report; its device record stays and ages out like any other.
- If both the host and the guest are linked to assets, a CMDB **hosts**
  relationship is kept up to date automatically. Relationships you draw by hand
  are never changed.
- VMware vCenter / ESXi is not supported yet.

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

**Reports** has four tabs (the builder needs licence module `reporting`):

- **Overview** — capital by category/department, lifecycle forecast
  (warranty and EOL/EOS), compliance & governance. Fill in `purchase_cost`,
  `warranty_end`, `eol_eos_date` and the governance fields to make these useful.
- **Library** — 35 ready-made reports: devices without working antivirus,
  firewall off, unencrypted disks, 3+ local admins, remote-access tools,
  missing a specific update, Windows builds, low RAM / low disk space, devices
  not seen in 30 days, virtual machines by host, powered-off VMs, VMs without
  their own inventory, warranties ending in 90 days, assets past end of life,
  contracts and licences expiring, open critical vulnerabilities, and more.
  Opening one loads it into the builder, where it can be adjusted and saved.
- **Builder** — choose the data (devices, installed software, updates,
  services, local accounts, antivirus, disks, monitors, device changes, virtual
  machines, assets, vulnerabilities, contracts, licences), add filters (match all or any), pick
  and order columns, or **group by** a field to get counts with a bar or pie
  chart. The preview updates as you edit. Device reports include the linked
  asset's tag, department, location, owner and criticality, so "Windows laptops
  in Finance with BitLocker off" is three filters. **Excel** / **CSV** export
  every matching row (up to 100,000).
- **Saved reports** — your reports plus those shared with everyone.
  Owners (and admins) can rename, share, pin to the dashboard, or delete.
  Administrators can **email a report on a schedule** (daily, weekly, monthly
  or cron) to a list of recipients as an Excel or CSV attachment, or send it now;
  the last result shows in the list and in Notifications → log.

The **Devices** and **Assets** pages have **Export to Excel**, which exports
every row matching the page's search and filters (not just the visible page).

Exports write text that starts with `=`, `+`, `-` or `@` with a leading
apostrophe, so values reported by endpoints can't run as spreadsheet formulas.

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
