"""Report builder: engine, library, saved reports, permissions, exports, scheduled email."""
import io
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from backend.licensing.state import license_manager
from backend.licensing.verifier import LicenseInfo, LicenseStatus
from backend.models.asset import Asset
from backend.models.notification import NotificationLog
from backend.models.saved_report import SavedReport
from backend.models.user import User
from backend.reporting.library import LIBRARY
from backend.schemas.inventory import InventoryReport
from backend.services.inventory_service import InventoryService
from backend.services.notification_service import NotificationService
from backend.utils.security import create_access_token, get_password_hash


def _report(host, *, ram, av_ok=True, software=(), patches=(), serial=None, admins=1):
    return InventoryReport.model_validate({
        "schema_version": 2, "hostname": host, "os_name": "Microsoft Windows 11 Pro", "os_build": "22631.4317",
        "hardware": {"serial_number": serial or f"SN-{host}", "manufacturer": "Dell Inc.", "model": "Latitude 7440",
                     "ram_gb": ram},
        "software": [{"name": n, "version": "1.0"} for n in software],
        "patches": [{"id": p} for p in patches],
        "local_accounts": [{"name": f"admin{i}", "is_admin": True} for i in range(admins)],
        "security": {"antivirus": [{"name": "Defender", "enabled": av_ok, "up_to_date": True}]},
    })


@pytest.fixture
async def seeded(api):
    async with api.session_factory() as s:
        await InventoryService.ingest(s, "agent", _report("PC-A", ram=4, av_ok=False, software=["Google Chrome", "TeamViewer"],
                                                         patches=["KB5034441"], admins=3))
        await InventoryService.ingest(s, "agent", _report("PC-B", ram=16, software=["Zoom"]))
        await InventoryService.ingest(s, "agent", _report("=HYPERLINK(\"http://evil\")", ram=8, software=["Zoom"]))
        today = date.today()
        s.add_all([
            Asset(asset_tag="AST-1", name="Laptop A", category="hardware", department="Finance",
                  warranty_end=today + timedelta(days=30), criticality="critical", monitoring_status="not_monitored"),
            Asset(asset_tag="AST-2", name="Laptop B", category="hardware", department="Finance",
                  warranty_end=today + timedelta(days=400), eol_eos_date=today - timedelta(days=5)),
            Asset(asset_tag="AST-3", name="Server", category="hardware", department=None),
        ])
        await s.commit()
    return api


async def _run(api, definition, **kw):
    r = await api.post("/api/reports/run", json={"definition": definition, **kw})
    return r


async def _rows(api, definition, key="hostname"):
    r = await _run(api, definition)
    assert r.status_code == 200, r.text
    return sorted(str(row[key]) for row in r.json()["data"]["rows"])


# ── engine ──
async def test_every_builtin_report_runs(seeded):
    for item in LIBRARY:
        r = await _run(seeded, item["definition"])
        assert r.status_code == 200, (item["id"], r.text)


async def test_filters_by_type(seeded):
    dev = lambda *filters, **kw: {"entity": "devices", "columns": ["hostname"],  # noqa: E731
                                  "filters": [dict(field=f, op=o, value=v) for f, o, v in filters], **kw}
    assert await _rows(seeded, dev(("ram_gb", "lt", 8))) == ["PC-A"]
    assert await _rows(seeded, dev(("antivirus_ok", "is_false", None))) == ["PC-A"]
    assert await _rows(seeded, dev(("has_software", "has", "teamviewer"))) == ["PC-A"]
    assert await _rows(seeded, dev(("has_patch", "has_not", "KB5034441"))) == ["=HYPERLINK(\"HTTP://EVIL\")", "PC-B"]
    assert await _rows(seeded, dev(("hostname", "in", "pc-a, PC-B"))) == ["PC-A", "PC-B"]
    assert await _rows(seeded, dev(("ram_gb", "gte", 16), ("local_admin_count", "gte", 3), match="any")) \
        == ["PC-A", "PC-B"]
    assert await _rows(seeded, dev(("ram_gb", "gte", 16), ("local_admin_count", "gte", 3))) == []
    assets = lambda *filters: {"entity": "assets", "columns": ["asset_tag"],  # noqa: E731
                               "filters": [dict(field=f, op=o, value=v) for f, o, v in filters]}
    assert await _rows(seeded, assets(("warranty_end", "within_next_days", 90)), "asset_tag") == ["AST-1"]
    assert await _rows(seeded, assets(("eol_eos_date", "is_past", None)), "asset_tag") == ["AST-2"]
    assert await _rows(seeded, assets(("department", "is_empty", None)), "asset_tag") == ["AST-3"]
    assert await _rows(seeded, assets(("criticality", "in", "critical,high")), "asset_tag") == ["AST-1"]


async def test_device_report_with_asset_fields(seeded):
    """The plan's acceptance example: Windows laptops in Finance with BitLocker off."""
    from backend.models.device import Device
    async with seeded.session_factory() as s:
        pc_a = (await s.execute(select(Device).where(Device.hostname == "PC-A"))).scalars().one()
        a1 = (await s.execute(select(Asset).where(Asset.asset_tag == "AST-1"))).scalars().one()
        a1.device_id = pc_a.id
        await s.commit()
    defn = {"entity": "devices", "columns": ["hostname", "department", "asset_tag"],
            "filters": [{"field": "os_name", "op": "contains", "value": "Windows"},
                        {"field": "department", "op": "eq", "value": "finance"},
                        {"field": "disk_encrypted", "op": "is_unknown", "value": None}]}
    r = (await _run(seeded, defn)).json()["data"]
    assert [(row["hostname"], row["department"], row["asset_tag"]) for row in r["rows"]] == [("PC-A", "Finance", "AST-1")]
    grouped = (await _run(seeded, {"entity": "devices", "group_by": "department"})).json()["data"]
    assert {(g["value"], g["count"]) for g in grouped["groups"]} == {("Finance", 1), (None, 2)}


async def test_search_matches_list_page_fields(seeded):
    assert await _rows(seeded, {"entity": "devices", "columns": ["hostname"], "search": "pc-"}) == ["PC-A", "PC-B"]
    assert await _rows(seeded, {"entity": "devices", "columns": ["hostname"], "search": "pc-",
                                "filters": [{"field": "ram_gb", "op": "gt", "value": 8}]}) == ["PC-B"]
    assert await _rows(seeded, {"entity": "assets", "columns": ["asset_tag"], "search": "server"}, "asset_tag") == ["AST-3"]


async def test_group_by_sort_and_paging(seeded):
    r = (await _run(seeded, {"entity": "software", "group_by": "name"})).json()["data"]
    assert r["kind"] == "groups" and r["groups"][0] == {"value": "Zoom", "count": 2}
    r = (await _run(seeded, {"entity": "devices", "columns": ["hostname", "ram_gb"], "sort": "ram_gb",
                             "sort_dir": "desc"}, size=2)).json()["data"]
    assert r["total"] == 3 and [row["ram_gb"] for row in r["rows"]] == [16, 8]
    assert r["link"] == "device" and r["rows"][0]["_link_id"]


@pytest.mark.parametrize("definition, message", [
    ({"entity": "users"}, "Unknown report entity"),
    ({"entity": "devices", "columns": ["password"]}, "no field"),
    ({"entity": "devices", "filters": [{"field": "ram_gb", "op": "contains", "value": "8"}]}, "doesn't apply"),
    ({"entity": "devices", "filters": [{"field": "ram_gb", "op": "lt", "value": "lots"}]}, "not a number"),
    ({"entity": "devices", "columns": ["has_software"]}, "only be used as a filter"),
    ({"entity": "assets", "filters": [{"field": "criticality", "op": "eq", "value": "urgent"}]}, "must be one of"),
])
async def test_invalid_definitions_are_rejected(seeded, definition, message):
    r = await _run(seeded, definition)
    assert r.status_code == 400 and message in r.json()["detail"]


async def test_licensing(api, monkeypatch):
    base = {"max_assets": 10, "max_users": 10}
    monkeypatch.setattr(license_manager, "_info", LicenseInfo(
        LicenseStatus.VALID, claims={**base, "modules": ["assets", "reporting"]}))
    r = await _run(api, {"entity": "contracts"})
    assert r.status_code == 403 and "contracts" in r.json()["detail"]
    monkeypatch.setattr(license_manager, "_info", LicenseInfo(LicenseStatus.VALID, claims={**base, "modules": ["assets"]}))
    assert (await _run(api, {"entity": "devices"})).status_code == 403


# ── saved reports & permissions ──
async def _user(api, name, role):
    async with api.session_factory() as s:
        s.add(User(username=name, email=f"{name}@t.local", hashed_password=get_password_hash("x"), role=role))
        await s.commit()
    return {"Authorization": f"Bearer {create_access_token(name)}"}


DEF = {"entity": "devices", "columns": ["hostname", "ram_gb"], "filters": [{"field": "ram_gb", "op": "lt", "value": 8}]}


async def test_saved_report_visibility_and_ownership(seeded):
    viewer = await _user(seeded, "vera", "viewer")
    other = await _user(seeded, "otto", "viewer")
    mine = (await seeded.post("/api/reports/saved", json={"name": "Low RAM", "definition": DEF},
                              headers=viewer)).json()["data"]
    assert [r["name"] for r in (await seeded.get("/api/reports/saved", headers=other)).json()["data"]] == []
    assert (await seeded.post(f"/api/reports/saved/{mine['id']}/run", headers=other)).status_code == 404

    await seeded.patch(f"/api/reports/saved/{mine['id']}", json={"shared": True}, headers=viewer)
    shared = (await seeded.get("/api/reports/saved", headers=other)).json()["data"]
    assert shared[0]["name"] == "Low RAM" and shared[0]["can_edit"] is False
    assert (await seeded.post(f"/api/reports/saved/{mine['id']}/run", headers=other)).json()["data"]["total"] == 1
    assert (await seeded.patch(f"/api/reports/saved/{mine['id']}", json={"name": "Mine now"},
                               headers=other)).status_code == 403
    assert (await seeded.delete(f"/api/reports/saved/{mine['id']}", headers=other)).status_code == 403
    # admins can manage any shared report
    assert (await seeded.patch(f"/api/reports/saved/{mine['id']}", json={"pinned": True})).status_code == 200


async def test_scheduling_is_admin_only_and_validated(seeded):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from backend.services import scheduler_service
    viewer = await _user(seeded, "vera", "viewer")
    rid = (await seeded.post("/api/reports/saved", json={"name": "Weekly", "definition": DEF},
                             headers=viewer)).json()["data"]["id"]
    r = await seeded.patch(f"/api/reports/saved/{rid}", json={"schedule_cron": "0 7 * * 1",
                                                              "recipients": ["a@corp.local"]}, headers=viewer)
    assert r.status_code == 403
    r = await seeded.patch(f"/api/reports/saved/{rid}", json={"schedule_cron": "0 7 * * 1"})
    assert r.status_code == 400 and "recipient" in r.json()["detail"]
    r = await seeded.patch(f"/api/reports/saved/{rid}", json={"recipients": ["not-an-email"]})
    assert r.status_code == 400
    r = await seeded.patch(f"/api/reports/saved/{rid}", json={"recipients": ["a@corp.local"], "schedule_cron": "every monday"})
    assert r.status_code == 400

    svc = scheduler_service.SchedulerService()
    svc.scheduler = AsyncIOScheduler()
    r = await seeded.patch(f"/api/reports/saved/{rid}", json={"recipients": ["a@corp.local"], "schedule_cron": "0 7 * * 1"})
    assert r.status_code == 200 and r.json()["data"]["schedule_cron"] == "0 7 * * 1"
    async with seeded.session_factory() as s:
        await svc.reload_jobs(s)
    job = svc.scheduler.get_job(f"report_{rid}")
    assert job.func_ref == "backend.services.scheduler_service:run_scheduled_report"


# ── exports & email ──
async def test_xlsx_and_csv_exports_neutralise_formulas(seeded):
    defn = {"entity": "devices", "columns": ["hostname", "ram_gb", "collected_at"], "sort": "hostname"}
    r = await seeded.post("/api/reports/export", json={"definition": defn, "name": "All devices"})
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.xlsx"')
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Report"]
    assert [c.value for c in ws[1]] == ["Hostname", "RAM (GB)", "Inventory date"]
    hostnames = [ws.cell(row=i, column=1).value for i in range(2, 5)]
    assert hostnames[0].startswith("'=HYPERLINK")         # stored as text, not a formula
    assert ws.cell(row=2, column=1).data_type == "s"
    assert ws.cell(row=3, column=2).value == 4
    assert wb["About"]["B1"].value == "All devices"

    r = await seeded.post("/api/reports/export", json={"definition": defn, "name": "All", "format": "csv"})
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "Hostname,RAM (GB),Inventory date"
    assert "'=HYPERLINK" in text


async def test_send_report_attaches_file_and_logs(seeded, monkeypatch):
    sent = []

    async def fake_send(db, subject, body, recipients, attachments=()):
        sent.append((subject, body, recipients, attachments))
    monkeypatch.setattr(NotificationService, "send_email", staticmethod(fake_send))

    rid = (await seeded.post("/api/reports/saved", json={"name": "Low RAM", "definition": DEF})).json()["data"]["id"]
    await seeded.patch(f"/api/reports/saved/{rid}", json={"recipients": ["it@corp.local"]})
    r = await seeded.post(f"/api/reports/saved/{rid}/send")
    assert r.status_code == 200 and "1 row" in r.json()["data"]
    subject, body, recipients, attachments = sent[0]
    assert recipients == ["it@corp.local"] and "RAM (GB) < 8" in body
    fname, content, mime = attachments[0]
    assert fname.startswith("low-ram-") and fname.endswith(".xlsx") and content[:2] == b"PK"
    async with seeded.session_factory() as s:
        log = (await s.execute(select(NotificationLog))).scalars().one()
        assert log.rule_type == "scheduled_report" and log.status == "sent"
        assert (await s.get(SavedReport, rid)).last_status.startswith("sent")


async def test_pinned_reports_for_dashboard(seeded):
    await seeded.post("/api/reports/saved", json={"name": "By model", "pinned": True,
                                                  "definition": {"entity": "devices", "group_by": "model", "chart": "bar"}})
    pinned = (await seeded.get("/api/reports/pinned")).json()["data"]
    assert pinned[0]["name"] == "By model" and pinned[0]["chart"] == "bar"
    assert pinned[0]["result"]["groups"][0]["count"] == 3
