"""Credentialed scanning: credential rules, scan-run integration, API scope, WinRM error mapping."""
import pytest
import requests
from sqlalchemy import select

from backend.connectors.network_scan.connector import NetworkScanConnector
from backend.models.inventory import DeviceInventory
from backend.models.scan_credential import ScanCredential
from backend.models.ssh_host_key import SshHostKey
from backend.schemas.inventory import InventoryReport
from backend.scanning import credentialed
from backend.scanning.collectors import CollectorError, CredentialInput
from backend.scanning.collectors import winrm as winrm_collector
from backend.scanning.runner import scan_runner
from tests.conftest import make_raw


def _cred(i, cred_type="ssh_password"):
    return CredentialInput(i, cred_type, "u", {}, {"password": "p"})


def _report(hostname="LAB-01"):
    return InventoryReport(hostname=hostname, os_name="Ubuntu", collector_version="2.0.0",
                           hardware={"serial_number": f"SN-{hostname}"},
                           software=[{"name": "openssh-server", "version": "9.6"}])


@pytest.fixture
def fake(monkeypatch):
    """Scripted collector: {credential id: report or error code}; records the call order."""
    calls, script = [], {}

    async def run(method, host, cred, keys):
        calls.append((method, cred.id))
        outcome = script.get(cred.id, "auth_failed")
        if isinstance(outcome, str):
            raise CollectorError(outcome, "scripted")
        return outcome

    async def reachable(host, method, creds):
        return script.get(f"reach:{method}", True)

    monkeypatch.setattr(credentialed, "_run", run)
    monkeypatch.setattr(credentialed, "_reachable", reachable)
    return calls, script


# ── credential rules ──
async def test_stops_at_first_success(fake):
    calls, script = fake
    script[2] = _report()
    out = await credentialed.inventory_host("10.0.0.5", ["ping", "ssh"], [_cred(1), _cred(2), _cred(3)], None)
    assert out.report is not None and out.credential_id == 2 and out.method == "ssh"
    assert calls == [("ssh", 1), ("ssh", 2)]


async def test_last_working_credential_goes_first(fake):
    calls, script = fake
    script[3] = _report()
    out = await credentialed.inventory_host("10.0.0.5", ["ssh"], [_cred(1), _cred(2), _cred(3)], None,
                                            preferred_credential_id=3)
    assert calls == [("ssh", 3)] and out.credential_id == 3


async def test_at_most_three_attempts_per_method(fake):
    calls, _ = fake
    creds = [_cred(i) for i in range(1, 7)]
    out = await credentialed.inventory_host("10.0.0.5", ["ssh"], creds, None)
    assert calls == [("ssh", 1), ("ssh", 2), ("ssh", 3)]
    assert out.report is None and out.error_code == "auth_failed"


async def test_unreachable_moves_to_next_method(fake):
    calls, script = fake
    script[1] = "unreachable"
    script[9] = _report()
    creds = [_cred(1, "windows"), _cred(2, "windows"), _cred(9, "snmp_v2c")]
    out = await credentialed.inventory_host("10.0.0.5", ["winrm", "snmp"], creds, None)
    assert calls == [("winrm", 1), ("snmp", 9)]       # credential 2 not tried: service unreachable
    assert out.method == "snmp"


async def test_methods_without_service_or_credentials_are_skipped(fake):
    calls, script = fake
    script["reach:winrm"] = False
    out = await credentialed.inventory_host("10.0.0.5", ["winrm", "ssh"], [_cred(1, "windows")], None)
    assert calls == [] and out.attempts == []


async def test_host_key_change_is_not_retried_with_other_credentials(fake):
    calls, script = fake
    script[1] = "host_key_changed"
    out = await credentialed.inventory_host("10.0.0.5", ["ssh"], [_cred(1), _cred(2)], None)
    assert calls == [("ssh", 1)] and out.error_code == "host_key_changed"


# ── scan run integration ──
async def _ssh_target(api, credential_ids):
    r = await api.post("/api/scan/targets", json={
        "name": "Lab", "target_type": "cidr", "value": "10.7.0.0/29", "methods": ["ping", "ssh"],
        "credential_ids": credential_ids})
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _ssh_credential(api, name="lab-ssh"):
    r = await api.post("/api/scan/credentials", json={
        "name": name, "cred_type": "ssh_password", "username": "scan", "secret": {"password": "pw"}})
    return r.json()["data"]


async def test_scan_run_inventories_responsive_hosts(api, monkeypatch):
    async def sweep(self, config):
        return [make_raw(source_uid=f"netscan-{ip}", hostname=None, fqdn=None, ip_addresses=[ip], mac_addresses=[])
                for ip in ("10.7.0.2", "10.7.0.3")]
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", sweep)

    async def fake_inventory(host, methods, creds, keys, preferred=None):
        out = credentialed.HostOutcome(attempts=[credentialed.Attempt("ssh", creds[0].id)], method="ssh",
                                       credential_id=creds[0].id, duration_ms=12)
        if host == "10.7.0.2":
            out.report = _report("LAB-02")
        else:
            out.error_code, out.error_message = "auth_failed", CollectorError("auth_failed").message
            out.attempts[0].code = "auth_failed"
        return out
    monkeypatch.setattr("backend.scanning.runner.inventory_host", fake_inventory)

    cred = await _ssh_credential(api)
    target = await _ssh_target(api, [cred["id"]])
    run_id = (await api.post(f"/api/scan/targets/{target['id']}/run")).json()["data"]["run_id"]
    await scan_runner.wait(run_id)

    run = (await api.get(f"/api/scan/runs/{run_id}")).json()["data"]
    assert run["status"] == "completed", run
    assert (run["hosts_alive"], run["hosts_inventoried"], run["hosts_failed"]) == (2, 1, 1)
    by_ip = {h["ip"]: h for h in run["hosts"]}
    assert by_ip["10.7.0.2"]["status"] == "inventoried" and by_ip["10.7.0.2"]["hostname"] == "LAB-02"
    assert by_ip["10.7.0.2"]["credential_name"] == "lab-ssh"
    assert by_ip["10.7.0.3"]["status"] == "failed" and by_ip["10.7.0.3"]["error_code"] == "auth_failed"
    assert "Check the username" in by_ip["10.7.0.3"]["error_message"]

    async with api.session_factory() as s:
        inv = (await s.execute(select(DeviceInventory))).scalars().one()
        assert inv.source == "ssh"
        # merged into the device the sweep created for 10.7.0.2, not a duplicate
        assert inv.device_id == by_ip["10.7.0.2"]["device_id"]
        c = await s.get(ScanCredential, cred["id"])
        assert c.last_used_at is not None and c.last_success_at is not None


async def test_targets_without_credentials_stay_sweep_only(api, monkeypatch):
    async def sweep(self, config):
        return [make_raw(source_uid="netscan-10.7.0.2", hostname="X", ip_addresses=["10.7.0.2"])]
    monkeypatch.setattr(NetworkScanConnector, "fetch_devices", sweep)

    async def must_not_run(*a, **k):
        raise AssertionError("credentialed step ran without credentials")
    monkeypatch.setattr("backend.scanning.runner.inventory_host", must_not_run)
    target = await _ssh_target(api, [])
    run_id = (await api.post(f"/api/scan/targets/{target['id']}/run")).json()["data"]["run_id"]
    await scan_runner.wait(run_id)
    run = (await api.get(f"/api/scan/runs/{run_id}")).json()["data"]
    assert run["status"] == "completed" and run["hosts"][0]["status"] == "alive"


# ── API: credential test scope, host keys, AD targets ──
async def test_credential_test_is_limited_to_assigned_targets(api, monkeypatch):
    seen = []

    async def fake_test(host, cred, keys):
        seen.append(host)
        return {"method": "ssh", "hostname": "lab", "os": "Linux"}
    monkeypatch.setattr("backend.routers.scanning.test_credential", fake_test)

    cred = await _ssh_credential(api)
    r = await api.post(f"/api/scan/credentials/{cred['id']}/test", json={"host": "10.7.0.2"})
    assert r.status_code == 400 and "not inside an enabled scan target" in r.json()["detail"]

    await _ssh_target(api, [cred["id"]])
    r = await api.post(f"/api/scan/credentials/{cred['id']}/test", json={"host": "10.7.0.2"})
    assert r.status_code == 200 and r.json()["data"]["ok"] is True
    r = await api.post(f"/api/scan/credentials/{cred['id']}/test", json={"host": "10.99.0.1"})
    assert r.status_code == 400
    assert seen == ["10.7.0.2"]


async def test_credential_test_reports_failures(api, monkeypatch):
    async def failing(host, cred, keys):
        raise CollectorError("auth_failed", "user scan")
    monkeypatch.setattr("backend.routers.scanning.test_credential", failing)
    cred = await _ssh_credential(api)
    await _ssh_target(api, [cred["id"]])
    data = (await api.post(f"/api/scan/credentials/{cred['id']}/test", json={"host": "10.7.0.2"})).json()["data"]
    assert data["ok"] is False and data["error_code"] == "auth_failed"


async def test_ssh_host_keys_can_be_listed_and_forgotten(api):
    async with api.session_factory() as s:
        s.add(SshHostKey(host="10.7.0.2", port=22, key_type="ssh-ed25519", public_key="ssh-ed25519 AAAA",
                         fingerprint="SHA256:abc"))
        await s.commit()
    keys = (await api.get("/api/scan/ssh-host-keys")).json()["data"]
    assert keys[0]["fingerprint"] == "SHA256:abc"
    assert (await api.delete(f"/api/scan/ssh-host-keys/{keys[0]['id']}")).status_code == 200
    assert (await api.get("/api/scan/ssh-host-keys")).json()["data"] == []


async def test_ad_target_needs_the_ad_connector(api):
    r = await api.post("/api/scan/targets/preview", json={"target_type": "ad", "value": "*"})
    assert r.status_code == 400 and "Active Directory connector" in r.json()["detail"]


# ── WinRM error mapping (no Windows host needed) ──
class _FakeClient:
    behaviour = None

    def __init__(self, *a, **k):
        pass

    def execute_ps(self, script):
        assert "-DryRun" in script and "[scriptblock]::Create(@'" in script
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour, None, False


@pytest.mark.parametrize("exc, code", [
    (requests.exceptions.ConnectionError("refused"), "unreachable"),
    (requests.exceptions.SSLError("self signed"), "tls_untrusted"),
    (requests.exceptions.ReadTimeout("slow"), "timeout"),
])
async def test_winrm_errors_are_classified(monkeypatch, exc, code):
    monkeypatch.setattr(winrm_collector, "Client", _FakeClient)
    monkeypatch.setattr(winrm_collector, "_choose_transport", lambda host, cred: (5985, False))
    _FakeClient.behaviour = exc
    with pytest.raises(CollectorError) as err:
        await winrm_collector.collect("10.0.0.9", _cred(1, "windows"))
    assert err.value.code == code


async def test_winrm_auth_failure(monkeypatch):
    from pypsrp.exceptions import AuthenticationError
    monkeypatch.setattr(winrm_collector, "Client", _FakeClient)
    monkeypatch.setattr(winrm_collector, "_choose_transport", lambda host, cred: (5985, False))
    _FakeClient.behaviour = AuthenticationError("Failed to authenticate the user with ntlm")
    with pytest.raises(CollectorError) as err:
        await winrm_collector.collect("10.0.0.9", _cred(1, "windows"))
    assert err.value.code == "auth_failed"


async def test_winrm_parses_agent_output(monkeypatch):
    monkeypatch.setattr(winrm_collector, "Client", _FakeClient)
    monkeypatch.setattr(winrm_collector, "_choose_transport", lambda host, cred: (5986, True))
    _FakeClient.behaviour = ('WARNING: x\n{"schema_version": 2, "hostname": "WIN-01", '
                             '"os_name": "Microsoft Windows Server 2022 Standard", "software": []}')
    report = await winrm_collector.collect("10.0.0.9", _cred(1, "windows"))
    assert report.hostname == "WIN-01" and report.software == []
