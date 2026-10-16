"""Inventory/changes/endpoint-health API, agent fleet & downloads, risky-change alerts, retention."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.models.agent import AgentToken
from backend.models.inventory import DeviceChange
from backend.models.notification import AlertRule
from backend.services.agent_service import LATEST_AGENT_VERSION
from backend.services.notification_service import NotificationService
from backend.services.retention_service import RetentionService
from tests.test_inventory_sections import BASE

TOKEN = "k" * 43


async def _agent_report(api, **overrides):
    async with api.session_factory() as s:
        if not (await s.execute(select(AgentToken))).scalars().first():
            s.add(AgentToken(token=TOKEN, name="t"))
            await s.commit()
    r = await api.post("/api/ingest/agent", json={**BASE, **overrides}, headers={"X-Agent-Token": TOKEN})
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_device_inventory_and_changes(api):
    device_id = (await _agent_report(api))["device_id"]
    await _agent_report(api, local_accounts=BASE["local_accounts"] + [{"name": "eve", "is_admin": True}])

    inv = (await api.get(f"/api/devices/{device_id}/inventory")).json()["data"]
    assert inv["summary"]["model"] == "Latitude 7440" and inv["summary"]["local_admin_count"] == 2
    assert [p["patch_id"] for p in inv["patches"]] == ["KB5034441"]
    assert {a["name"] for a in inv["local_accounts"]} == {"Administrator", "alice", "eve"}
    assert inv["volumes"][0]["encrypted"] is True

    changes = (await api.get(f"/api/devices/{device_id}/changes")).json()["data"]
    assert changes["total"] == 1 and changes["items"][0]["item"] == "eve"
    assert (await api.get(f"/api/devices/{device_id}/changes?category=bogus")).status_code == 400

    fleet = (await api.get("/api/changes?severity=warning")).json()["data"]
    assert fleet[0]["hostname"] == "PC-42" and fleet[0]["severity"] == "warning"


async def test_device_without_inventory(api):
    async with api.session_factory() as s:
        from backend.models.device import Device
        d = Device(hostname="PRINTER", ip_addresses=[], mac_addresses=[])
        s.add(d)
        await s.commit()
        device_id = d.id
    assert (await api.get(f"/api/devices/{device_id}/inventory")).json()["data"] == {"summary": None}
    assert (await api.get("/api/devices/999999/inventory")).status_code == 404


async def test_endpoint_health_counts_match_device_filter(api):
    await _agent_report(api, security={**BASE["security"], "firewall": [{"profile": "Public", "enabled": False}]})
    health = (await api.get("/api/dashboard/endpoint-health")).json()["data"]
    assert health["inventoried"] == 1
    assert health["counts"]["firewall_off"] == 1 and health["counts"]["no_antivirus"] == 0
    listed = (await api.get("/api/devices?health=firewall_off")).json()["data"]
    assert listed["total"] == 1 and listed["items"][0]["hostname"] == "PC-42"
    assert (await api.get("/api/devices?health=no_antivirus")).json()["data"]["total"] == 0
    assert (await api.get("/api/devices?health=nonsense")).status_code == 400


async def test_agent_fleet_flags_outdated_agents(api):
    await _agent_report(api, collector_version=LATEST_AGENT_VERSION)
    await _agent_report(api, hostname="OLD-PC", collector_version="1.0.0",
                        hardware={**BASE["hardware"], "serial_number": "OLD-1"})
    fleet = (await api.get("/api/agents/fleet")).json()["data"]
    by_host = {a["hostname"]: a for a in fleet["agents"]}
    assert fleet["latest_version"] == LATEST_AGENT_VERSION
    assert by_host["PC-42"]["outdated"] is False and by_host["OLD-PC"]["outdated"] is True


async def test_agent_downloads_are_public_and_whitelisted(api):
    r = await api.get("/api/agents/download/install_agent.sh", headers={"Authorization": ""})
    assert r.status_code == 200 and r.text.startswith("#!/bin/sh")
    assert (await api.get("/api/agents/download/..%2Fbackend%2Fconfig.py")).status_code == 404
    assert (await api.get("/api/agents/download/conftest.py")).status_code == 404


async def test_risky_changes_are_emailed_once(api, monkeypatch):
    sent = []

    async def fake_send(db, subject, body, recipients):
        sent.append(body)
    monkeypatch.setattr(NotificationService, "send_email", staticmethod(fake_send))

    await _agent_report(api)
    await _agent_report(api, local_accounts=BASE["local_accounts"] + [{"name": "mallory", "is_admin": True}])
    async with api.session_factory() as s:
        await NotificationService.ensure_default_rules(s)
        rule = (await s.execute(select(AlertRule).where(AlertRule.rule_type == "security_changes"))).scalar_one()
        rule.enabled, rule.recipients = True, ["secops@corp.local"]
        await s.commit()
        summary = await NotificationService.run_checks(s)
        assert summary["security_changes"].startswith("sent (1")
        assert "PC-42: new local admin mallory" in sent[0]
        # Already reported: a forced re-run finds nothing new.
        assert (await NotificationService.run_checks(s, force=True))["security_changes"] == "no matches"


async def test_retention_prunes_old_change_history(api):
    device_id = (await _agent_report(api))["device_id"]
    old = datetime.now(timezone.utc) - timedelta(days=400)
    async with api.session_factory() as s:
        s.add(DeviceChange(device_id=device_id, category="software", change_type="added", item="Old",
                           detected_at=old))
        s.add(DeviceChange(device_id=device_id, category="software", change_type="added", item="New"))
        await s.commit()
        assert (await RetentionService.run(s))["changes_pruned"] == 1
        assert [c.item for c in (await s.execute(select(DeviceChange))).scalars()] == ["New"]
