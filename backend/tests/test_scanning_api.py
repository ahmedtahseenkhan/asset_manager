"""Credential vault, scan targets and scan runs."""
import asyncio

from sqlalchemy import select, text

from backend.connectors.network_scan.connector import NetworkScanConnector
from backend.licensing.state import license_manager
from backend.licensing.verifier import LicenseInfo, LicenseStatus
from backend.models.device import Device
from backend.models.scan_run import ScanRun
from backend.scanning.runner import scan_runner
from tests.conftest import make_raw

WIN = {"name": "Domain admin", "cred_type": "windows", "username": r"CORP\svc-scan",
       "secret": {"password": "S3cret!pw"}}


async def _cred(api, **overrides):
    r = await api.post("/api/scan/credentials", json={**WIN, **overrides})
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _target(api, **overrides):
    body = {"name": "HQ LAN", "target_type": "cidr", "value": "10.9.0.0/29", **overrides}
    r = await api.post("/api/scan/targets", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── credentials ──
async def test_secrets_are_never_returned_and_encrypted_at_rest(api):
    created = await _cred(api)
    assert "secret" not in created and created["secrets_set"] == ["password"]
    listed = (await api.get("/api/scan/credentials")).json()["data"]
    assert "S3cret!pw" not in str(listed)
    async with api.session_factory() as s:
        stored = (await s.execute(text("SELECT secret FROM scan_credentials"))).scalar_one()
    assert "S3cret" not in stored


async def test_credential_validation(api):
    bad = [
        {**WIN, "secret": {}},                                              # missing password
        {**WIN, "username": ""},                                            # missing username
        {"name": "x", "cred_type": "telnet", "secret": {"password": "p"}},  # unknown type
        {"name": "v3", "cred_type": "snmp_v3", "username": "mon",
         "params": {"security_level": "authPriv"}, "secret": {"auth_password": "a"}},  # no priv
        {"name": "ssh", "cred_type": "ssh_password", "username": "root",
         "params": {"port": 70000}, "secret": {"password": "p"}},
    ]
    for body in bad:
        r = await api.post("/api/scan/credentials", json=body)
        assert r.status_code == 400, body


async def test_update_keeps_secrets_not_sent(api):
    cred = await _cred(api)
    r = await api.patch(f"/api/scan/credentials/{cred['id']}", json={"username": r"CORP\other"})
    assert r.status_code == 200 and r.json()["data"]["secrets_set"] == ["password"]
    async with api.session_factory() as s:
        from backend.models.scan_credential import ScanCredential
        row = await s.get(ScanCredential, cred["id"])
        assert row.secret == {"password": "S3cret!pw"} and row.username == r"CORP\other"


async def test_duplicate_credential_name_conflicts(api):
    await _cred(api)
    assert (await api.post("/api/scan/credentials", json=WIN)).status_code == 409


# ── targets ──
async def test_target_validation_and_preview(api):
    r = await api.post("/api/scan/targets/preview",
                       json={"target_type": "range", "value": "10.0.0.1-10", "exclusions": "10.0.0.5"})
    assert r.json()["data"]["count"] == 9
    for body in ({"value": "10.0.0.0/8"}, {"value": "nonsense"}, {"schedule_cron": "every day"},
                 {"methods": ["telnet"]}, {"credential_ids": [999]}):
        r = await api.post("/api/scan/targets", json={"name": "t", "target_type": "cidr",
                                                      "value": "10.0.0.0/24", **body})
        assert r.status_code == 400, body


async def test_credential_order_is_kept_and_can_be_reordered(api):
    a = await _cred(api, name="A")
    b = await _cred(api, name="B")
    t = await _target(api, credential_ids=[b["id"], a["id"]], methods=["winrm", "ping"])
    assert t["credential_ids"] == [b["id"], a["id"]]
    assert t["methods"] == ["ping", "winrm"]
    r = await api.patch(f"/api/scan/targets/{t['id']}", json={"credential_ids": [a["id"], b["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["credential_ids"] == [a["id"], b["id"]]


async def test_deleting_credential_removes_it_from_targets(api):
    a = await _cred(api, name="A")
    t = await _target(api, credential_ids=[a["id"]])
    assert (await api.delete(f"/api/scan/credentials/{a['id']}")).status_code == 200
    targets = (await api.get("/api/scan/targets")).json()["data"]
    assert targets[0]["id"] == t["id"] and targets[0]["credential_ids"] == []


# ── runs ──
async def test_run_sweeps_target_and_records_hosts(api, monkeypatch):
    seen = {}

    async def fake_fetch(self, config):
        seen.update(config)
        return [make_raw(source_uid="netscan-10.9.0.2", hostname="PRINTER-1", fqdn=None,
                         ip_addresses=["10.9.0.2"], mac_addresses=[])]
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", fake_fetch)

    t = await _target(api, exclusions="10.9.0.6")
    r = await api.post(f"/api/scan/targets/{t['id']}/run")
    run_id = r.json()["data"]["run_id"]
    await scan_runner.wait(run_id)

    assert seen["addresses"] == ["10.9.0.1", "10.9.0.2", "10.9.0.3", "10.9.0.4", "10.9.0.5"]
    run = (await api.get(f"/api/scan/runs/{run_id}")).json()["data"]
    assert run["status"] == "completed", run
    assert (run["hosts_total"], run["hosts_alive"]) == (5, 1)
    assert run["hosts"][0]["ip"] == "10.9.0.2" and run["hosts"][0]["device_id"]
    target = (await api.get("/api/scan/targets")).json()["data"][0]
    assert target["last_status"] == "completed"
    async with api.session_factory() as s:
        assert (await s.execute(select(Device.hostname))).scalar_one() == "PRINTER-1"


async def test_one_run_per_target_and_cancel(api, monkeypatch):
    release = asyncio.Event()

    async def slow_fetch(self, config):
        await release.wait()
        return []
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", slow_fetch)

    t = await _target(api)
    run_id = (await api.post(f"/api/scan/targets/{t['id']}/run")).json()["data"]["run_id"]
    await asyncio.sleep(0.05)
    assert (await api.post(f"/api/scan/targets/{t['id']}/run")).status_code == 409
    assert (await api.delete(f"/api/scan/targets/{t['id']}")).status_code == 409

    assert (await api.post(f"/api/scan/runs/{run_id}/cancel")).status_code == 200
    await scan_runner.wait(run_id)
    run = (await api.get(f"/api/scan/runs/{run_id}")).json()["data"]
    assert run["status"] == "cancelled"
    assert (await api.post(f"/api/scan/runs/{run_id}/cancel")).status_code == 409


async def test_failed_sweep_is_recorded(api, monkeypatch):
    async def broken(self, config):
        raise RuntimeError("The 'ping' command is not installed on the server")
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", broken)
    t = await _target(api)
    run_id = (await api.post(f"/api/scan/targets/{t['id']}/run")).json()["data"]["run_id"]
    await scan_runner.wait(run_id)
    run = (await api.get(f"/api/scan/runs/{run_id}")).json()["data"]
    assert run["status"] == "failed" and "ping" in run["error"]


async def test_restart_closes_interrupted_runs(api):
    t = await _target(api)
    async with api.session_factory() as s:
        s.add(ScanRun(target_id=t["id"], target_name="HQ LAN", trigger="manual", status="running"))
        await s.commit()
    assert await scan_runner.recover_interrupted() == 1
    runs = (await api.get("/api/scan/runs")).json()["data"]
    assert runs[0]["status"] == "failed" and "restart" in runs[0]["error"]


# ── licensing ──
async def test_requires_discovery_plus_module(api, monkeypatch):
    monkeypatch.setattr(license_manager, "_info", LicenseInfo(
        LicenseStatus.VALID, claims={"modules": ["assets", "connectors"], "max_assets": 10, "max_users": 10}))
    r = await api.get("/api/scan/targets")
    assert r.status_code == 403 and "discovery_plus" in r.json()["detail"]
