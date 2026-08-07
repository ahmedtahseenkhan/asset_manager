# License Signer (vendor-side only)

This directory is the **vendor's** tooling for issuing customer licenses.
It must NEVER be included in a customer deployment or Docker image.

- `keys/dev/` contains a **development-only** keypair, committed so the dev
  environment works out of the box. For production, generate a fresh keypair
  (`python sign_license.py keygen --out-dir keys/prod`), keep the private key
  offline (HSM / encrypted vault), and bake the new public key into
  `backend/licensing/public_key.pem` before building release images.

## Issue a customer license

```bash
python sign_license.py issue \
  --private-key keys/prod/license_private.pem \
  --customer "Acme Corp" \
  --expires 2027-12-31 \
  --max-assets 5000 --max-users 50 \
  --modules assets,cmdb,contracts,entitlements,notifications,connectors \
  --out acme.lic
```

Send the `.lic` file to the customer. They install it via the admin UI
(Administration → License) or by placing it at the path configured by
`LICENSE_FILE` in `backend/.env`. Validation is fully offline (Ed25519
signature against the embedded public key) — works air-gapped.
