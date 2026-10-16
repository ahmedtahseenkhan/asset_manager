# IT Asset Manager — Administrator Guide

Fully on-premises IT asset management. No external cloud services are required
for any core function; the system runs air-gapped.

## 1. Installation (Docker Compose)

Requirements: Docker Engine + Compose v2, 2 GB RAM, ~5 GB disk.

```bash
./deploy/install/install.sh
```

The installer generates strong secrets into `deploy/docker/.env` (mode 600),
builds three images (postgres / api / web), waits for health, and prompts you
to create the initial admin account. The UI is then at `http://<host>:8080`
(port configurable via `HTTP_PORT`).

### Air-gapped hosts

On a connected machine:

```bash
docker compose -f deploy/docker/compose.prod.yml build
docker save itam-api itam-web postgres:16-alpine | gzip > itam-images.tgz
```

Transfer `itam-images.tgz` + this repository to the target, `docker load -i
itam-images.tgz`, then run the installer — it will use the local images.

## 2. Licensing

The application requires a signed license file (`.lic`). Validation is fully
offline: an Ed25519 signature is checked against the public key baked into the
image. There is **no phone-home**.

- **Install/renew:** Administration → License → *Upload license file* (or place
  the file at the `LICENSE_FILE` path and restart).
- **States:** `valid` → `grace` (expired, still working, warning banner) →
  `expired`/`invalid` (reads still work; **writes are blocked** except login
  and license upload, so you can always recover).
- **Limits:** `max_assets`, `max_users`, and the enabled module list are
  enforced from the license claims.
- **Modules:** `assets`, `cmdb`, `contracts`, `entitlements`, `notifications`,
  `connectors`, `discovery_plus` (Scanning page: targets, credentials,
  credentialed scanning), `reporting`, `topology`, `cloud`, `ot`. A feature
  whose module is missing answers 403 with the module's name. Licences issued
  before `discovery_plus` existed need re-issuing to use the Scanning page.
- The License page shows current usage against limits.

## 3. Users & roles

| Role | Rights |
|---|---|
| `viewer` | read-only everywhere |
| `asset_manager` | create/edit assets, lifecycle, contracts, entitlements, reconciliation |
| `admin` | everything, incl. connectors, license, notifications, deletes, user admin |

Create users via `POST /api/auth/register` or the Admin page. The first admin
comes from the installer (`python -m backend.scripts.create_admin`).

## 4. Notifications

Administration → Notifications:

1. Configure your **on-prem SMTP relay** (password stored encrypted) and use
   *Test* to confirm delivery.
2. Enable the alert rules you want (contract renewals, asset warranties,
   software license expiry, application license expiry, risky device changes,
   OS end of support) with thresholds and recipients.

Checks run daily at 08:00 UTC; each rule sends at most one digest per day.
*Run checks now* triggers an immediate pass. Every send (or failure) is
recorded in the on-page log.

## 4a. End-of-life catalogue

OS and software end-of-support dates come from a catalogue bundled with each
release (`backend/lifecycle/eol_catalog.json`); nothing is fetched from the
internet. Status (out of support / ending soon) is worked out against today's
date, so it stays current without updates. Only new releases, or dates a vendor
announces later, need a newer catalogue.

- **Between releases:** Lifecycle → *Upload catalogue (JSON)* (admins). The file
  is validated before use; a mistake is reported with the product and field. The
  catalogue with the newest `published` date is used, so a release with a newer
  bundled catalogue supersedes an older upload. To add your own products, copy
  the bundled file, add entries, and raise `published`.
- **Recalculate now** re-applies the catalogue to every device. This also runs
  at startup, daily at 03:00 UTC, and for each device on each inventory report.
- Apple publishes no end-of-support dates for macOS. The catalogue treats a
  version as unsupported once the third newer version is released; versions
  still within that window have no date.
- The software catalogue (`backend/lifecycle/software_catalog.json`, product
  names, vendors and categories) ships with releases only.

## 5. Backups

```bash
# dump DB + license file, keep last 14
./deploy/backup/backup.sh /var/backups/itam 14

# restore (destructive, prompts for confirmation)
./deploy/backup/restore.sh /var/backups/itam/itam_db_<stamp>.sql.gz
```

Schedule the backup via cron. Also keep a copy of `deploy/docker/.env` — the
`ENCRYPTION_KEY` in it is required to decrypt stored connector credentials,
SMTP passwords, and entitlement license keys. **Losing that key means losing
those secrets.**

## 6. Audit trail integrity

Every mutating action is written to a hash-chained audit log
(`row_hash = sha256(prev_hash ‖ entry)`). To detect tampering:

```
GET /api/admin/audit-verify   →   {"intact": true, "checked": N, ...}
```

If a row is modified or deleted in the database, verification reports the
first broken entry. Run it periodically or after any suspected incident.

## 7. TLS / encryption in transit

The web container serves plain HTTP on the internal port. Terminate TLS in
front of it with your standard mechanism, e.g.:

- existing corporate reverse proxy / load balancer → forward to `:8080`;
- or mount certificates into the web container and extend
  `deploy/docker/nginx.conf` with a `listen 443 ssl;` server block.

Data at rest: Postgres volume (use disk/volume encryption per your policy) +
field-level Fernet encryption for all stored secrets.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| API unhealthy | `docker compose -f deploy/docker/compose.prod.yml logs api` |
| API won't start after an upgrade | look for a migration error in the api log; the schema was rolled back, so restore the previous image or contact support |
| "License expired/invalid" banner | License page → upload a current `.lic` |
| Writes rejected with 403 | license state or role — check License page and the user's role |
| Emails not arriving | Notifications → Test; check relay host/port/STARTTLS; see the alert log for errors |
| Audit verify reports broken | investigate DB access; restore from backup |
| Scanned host shows "failed" | open the run in Scanning → Scan history: each failed host shows the cause and the fix; then use **Test credential** on that host |

Logs are structured JSON on the api container's stdout — ship them to your
SIEM with your standard collector. No telemetry ever leaves the host.

## 8a. Preparing hosts for credentialed scanning

Credentialed scans (Scanning → targets with WinRM / SSH / SNMP ticked) read
inventory with accounts you store under **Scanning → Credentials**. Use
dedicated, least-privilege accounts and assign each credential only to the
targets it is meant for — a credential is never tried outside its targets, at
most 3 credentials per method are tried per host per run, and trying stops at
the first that works, so scans won't lock accounts out. After setting up an
account, use **Test credential** against one host before scheduling a scan.

**Windows — WinRM (TCP 5985 HTTP / 5986 HTTPS)**
- Enable WinRM on the hosts: Group Policy *Computer Configuration → Policies →
  Administrative Templates → Windows Components → Windows Remote Management →
  WinRM Service → Allow remote server management through WinRM* (restrict the
  IPv4 filter to this server), set the *Windows Remote Management* service to
  start automatically, and allow inbound TCP 5985 (or 5986) from this server in
  Windows Firewall. On a single host: `winrm quickconfig`.
- Account: a domain account that is a member of the local **Administrators**
  group on the targets (via Group Policy *Restricted Groups* / *Local Users and
  Groups*). Full inventory (BitLocker, TPM, all services) needs admin rights.
- Over HTTP the payload is still encrypted (NTLM/Kerberos message
  encryption). For HTTPS with a self-signed certificate, set the credential's
  *Verify TLS certificate* to *no*, or install your CA on this server.
- Hosts without WinRM: enable it as above, or install the agent instead.

**Linux / macOS / Unix — SSH (TCP 22, or the port set on the credential)**
- Account with password or key login. `python3` on the host gives full
  inventory; without it only basic details are collected.
- Serial numbers, hardware UUID and account lock state need root. Tick *Use
  sudo* on the credential and allow exactly the agent to run without a password:
  `scan-account ALL=(root) NOPASSWD: /usr/bin/python3` in `/etc/sudoers.d/itam`.
- Host keys are trusted the first time a host is scanned. If a host's key later
  changes, nothing is sent to it and the run says so; after confirming the host
  was rebuilt, remove its entry under Credentials → *Trusted SSH host keys*.

**Network devices and printers — SNMP (UDP 161)**
- Read-only access only (the scanner issues GET/WALK, never SET). Prefer
  SNMPv3 with authPriv (SHA/AES); for v1/v2c use a read-only community.
- Add this server to the device's SNMP access list. A wrong community and a
  missing ACL look identical (no response); a wrong SNMPv3 password is reported
  as a sign-in failure.
- **Network map** (licence module `topology`): include your switches and
  routers in an SNMP scan target. The same read-only access is used to read
  LLDP/CDP neighbours, the MAC address table and the ARP cache. Enable LLDP (or
  CDP) on switches so links are drawn. On Cisco switches without Q-BRIDGE-MIB,
  the MAC table is read per VLAN: for SNMPv3 the user needs access to the
  `vlan-*` contexts (`snmp-server group … context vlan- match prefix`).

**Hyper-V hosts.** Guests are read with the same agent or WinRM scan as the
host (`Get-VM` and the `root\virtualization\v2` WMI namespace). For WinRM,
the account needs local **Administrators** or **Hyper-V Administrators**
membership on the host. Guest IP addresses, FQDN and OS name come from
integration services, so they are only known for running guests with
integration services enabled.

**Docker networking.** In the standard install the API container reaches your
LAN through Docker's NAT: ping, WinRM, SSH and SNMP all work, but ARP-based
details (MAC addresses of hosts that don't run an agent) and broadcast name
lookups are not available. Always enter real subnets in scan targets.

## 9. Upgrades

```bash
git pull            # or unpack the new release
docker compose -f deploy/docker/compose.prod.yml up -d --build
```

Volumes (`pg_data`, `api_data`) persist across upgrades. Take a backup first.

**Database migrations run automatically** when the API starts. Each upgrade
applies in a single transaction, so a failed upgrade leaves the schema exactly
as it was. If several API containers start together, only one migrates and the
others wait. Installs from before migrations existed are adopted on their first
start: the log shows `adopting it at 0001_baseline`.

To run migrations by hand (e.g. before switching traffic over):

```bash
docker compose -f deploy/docker/compose.prod.yml run --rm api python -m backend.migrations
```

If the log warns `Database schema differs from the models`, the database was
changed by hand or a release is missing a migration. Contact support with that
log line before making further changes.
