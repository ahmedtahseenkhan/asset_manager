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
   software license expiry, application license expiry) with thresholds and
   recipients.

Checks run daily at 08:00 UTC; each rule sends at most one digest per day.
*Run checks now* triggers an immediate pass. Every send (or failure) is
recorded in the on-page log.

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

Logs are structured JSON on the api container's stdout — ship them to your
SIEM with your standard collector. No telemetry ever leaves the host.

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
