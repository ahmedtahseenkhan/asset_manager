# IT Asset Manager

Commercial, fully **on-premises** IT asset management (ITAM) with CMDB
relationships, lifecycle tracking, contracts & software entitlements,
connector-based discovery (AD / EDR), and offline license activation.
Runs air-gapped — no external cloud dependency.

## Features

- **License-key activation** — Ed25519-signed `.lic` files validated offline;
  enforced limits (max assets/users), per-module gating, graceful degradation
- **Asset inventory** — CRUD, custom fields, auto tags, lifecycle state machine
  (`requested → ordered → in_stock → deployed ⇄ maintenance → retired`)
- **Discovery & reconciliation** — connectors (Active Directory, CrowdStrike,
  Defender, McAfee, Symantec, mock) sync devices; adopt or link them to assets
- **CMDB** — directed relationships (depends_on, hosts, installed_on, …)
- **Contracts & entitlements** — renewal windows, seat tracking, encrypted keys
- **Notifications** — expiry digests via on-prem SMTP relay, daily schedule
- **Security** — RBAC (admin / asset_manager / viewer), Fernet field encryption,
  tamper-evident hash-chained audit log, JWT auth, rate limiting

## Development

```bash
docker compose up -d postgres                # dev DB on :5454
cd backend && uv venv .venv && uv pip install -r requirements.txt
cd .. && ./backend/.venv/bin/uvicorn backend.main:app --reload --port 8000
cd frontend && npm install && npm run dev    # UI on :5173
./backend/.venv/bin/python -m backend.dev_seed   # dev admin: admin/admin123
```

A dev license (`backend/license.lic`) and dev signing keypair
(`tools/license-signer/keys/dev/`) are committed so everything works out of
the box. **Generate a fresh keypair for production** — see
`tools/license-signer/README.md`.

## Production deployment

```bash
./deploy/install/install.sh
```

See [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) for air-gapped installs,
licensing operations, backups, TLS, and troubleshooting.

## Repository layout

```
backend/            FastAPI app (routers, services, models, licensing, connectors)
frontend/           React + Vite + Tailwind SPA
tools/license-signer/  VENDOR-ONLY license issuing CLI — never ship to customers
deploy/docker/      Dockerfiles, nginx config, production compose
deploy/install/     one-shot installer
deploy/backup/      pg_dump backup + restore scripts
docs/               administrator guide
```
