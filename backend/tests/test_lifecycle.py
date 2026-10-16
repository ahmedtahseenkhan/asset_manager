"""End-of-life catalogue matching, device lifecycle, catalogue upload, warranty
import, software categories, and the reports and alerts built on them."""
import copy
import io
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.correlator.correlator import Correlator
from backend.lifecycle import eol as eol_catalog
from backend.lifecycle.eol import Catalog, status
from backend.models.asset import Asset
from backend.models.lifecycle import DeviceLifecycle
from backend.models.software import InstalledSoftware
from backend.models.user import User
from backend.reporting.library import BY_ID
from backend.schemas.inventory import InventoryReport
from backend.services.inventory_service import InventoryService
from backend.services.lifecycle_service import LifecycleService
from backend.services.notification_service import NotificationService
from backend.services.software_normalizer import classify_software
from backend.services.warranty_import import parse_date
from backend.utils.security import create_access_token, get_password_hash
from tests.conftest import make_raw

CAT = Catalog.bundled()
TODAY = date.today()


@pytest.fixture(autouse=True)
def bundled_catalog():
    eol_catalog.use(Catalog.bundled())
    yield
    eol_catalog.use(Catalog.bundled())


# ── matching ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("os_name, os_version, os_build, title, eol", [
    ("Microsoft Windows 11 Pro", "10.0.22631", "22631.4317", "Windows 11 23H2 (Home/Pro)", "2025-11-11"),
    ("Microsoft Windows 11 Enterprise", "10.0.22631", "22631.4317", "Windows 11 23H2 (Enterprise/Education)", "2026-11-10"),
    ("Microsoft Windows 11 Pro Education", "10.0.26100", "26100.1", "Windows 11 24H2 (Home/Pro)", "2026-10-13"),
    ("Microsoft Windows 11 Education", "10.0.26100", "26100.1", "Windows 11 24H2 (Enterprise/Education)", "2027-10-12"),
    ("Microsoft Windows 11 IoT Enterprise LTSC", "10.0.26100", "26100.1", "Windows 11 LTSC 2024 (IoT)", "2034-10-10"),
    ("Microsoft Windows 10 Enterprise LTSC", "10.0.17763", "17763.1", "Windows 10 LTSC 2019", "2029-01-09"),
    ("Windows 10 Enterprise", "10.0 (19045)", None, "Windows 10 22H2", "2025-10-14"),            # AD
    ("Windows10", "10.0.19045.4529", None, "Windows 10 22H2", "2025-10-14"),                     # Defender
    ("Microsoft Windows 7 Professional", "6.1.7601", "7601", "Windows 7", "2020-01-14"),
    ("Microsoft Windows Server 2012 R2 Datacenter", "6.3.9600", "9600", "Windows Server 2012 R2", "2023-10-10"),
    ("Windows Server 2016 Standard", "10.0 (14393)", None, "Windows Server 2016", "2027-01-12"),
    ("Windows Server", "10.0.20348", None, "Windows Server 2022", "2031-10-14"),                   # by build
    ("macOS", "10.15.7", None, "macOS 10.15 Catalina", "2022-10-24"),
    ("macOS", "15.1", None, "macOS 15 Sequoia", None),
    ("Ubuntu", "20.04", "5.15.0-91-generic", "Ubuntu 20.04 LTS", "2025-05-31"),
    ("Ubuntu 22.04.4 LTS", None, None, "Ubuntu 22.04 LTS", "2027-04-30"),
    ("Red Hat Enterprise Linux Server", "7.9", None, "Red Hat Enterprise Linux 7", "2024-06-30"),
    ("CentOS Stream", "9", None, "CentOS Stream 9", "2027-05-31"),
    ("Debian GNU/Linux", "12", None, "Debian 12 bookworm", "2028-06-30"),
])
def test_os_matching(os_name, os_version, os_build, title, eol):
    m = CAT.match_os(os_name, os_version, os_build)
    assert m is not None and m.kind == "os"
    assert (m.title, m.eol) == (title, date.fromisoformat(eol) if eol else None)


@pytest.mark.parametrize("os_name, os_version", [
    ("Windows", None), ("Windows 10", None), ("Cisco IOS", "15.2"), ("Ubuntu", "21.10"), (None, "10.0.19045"),
])
def test_os_not_identified(os_name, os_version):
    assert CAT.match_os(os_name, os_version) is None


@pytest.mark.parametrize("name, version, title", [
    ("Microsoft Office Professional Plus 2016", "16.0.4266.1001", "Microsoft Office 2016"),
    ("Microsoft Office LTSC Professional Plus 2021 - en-us", None, "Microsoft Office 2021"),
    ("Microsoft 365 Apps for enterprise - en-us", None, None),
    ("Microsoft SQL Server 2016 (64-bit)", None, "Microsoft SQL Server 2016"),
    ("Microsoft SQL Server 2012 Native Client", None, None),
    ("Microsoft ASP.NET Core 6.0.36 - Shared Framework (x64)", None, ".NET 6.0"),
    ("Microsoft .NET Framework 4.8.1 SDK", None, None),
    ("Python 3.9.13 (64-bit)", "3.9.13150.0", "Python 3.9"),
    ("Python Launcher", None, None),
    ("Node.js", "18.17.1", "Node.js 18"),
    ("Adobe Acrobat Reader DC - MUI", None, None),
    ("Adobe Reader XI (11.0.23)", None, "Adobe Acrobat (classic) XI"),
    ("Adobe Flash Player 32 NPAPI", None, "Adobe Flash Player"),
    ("Google Chrome", "120.0", None),
])
def test_software_matching(name, version, title):
    m = CAT.match_software(name, version)
    assert (m.title if m else None) == title


def test_status():
    assert status(None, TODAY) == "supported"
    assert status(TODAY - timedelta(days=1), TODAY) == "unsupported"
    assert status(TODAY, TODAY) == "ending_soon"
    assert status(TODAY + timedelta(days=180), TODAY) == "ending_soon"
    assert status(TODAY + timedelta(days=181), TODAY) == "supported"


def _bundled_json() -> dict:
    return json.loads(eol_catalog.BUNDLED_PATH.read_text())


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema=2), "schema"),
    (lambda d: d.update(published="16/10/2026"), "YYYY-MM-DD"),
    (lambda d: d["products"][0].update(match="magic"), "must be one of"),
    (lambda d: d["products"][1].update(id=d["products"][0]["id"]), "duplicate id"),
    (lambda d: d["products"][-1].update(name_regex="(unclosed"), "invalid pattern"),
    (lambda d: d["products"][0]["cycles"][0].pop("eol"), "\"eol\" is required"),
])
def test_catalogue_validation(mutate, message):
    data = _bundled_json()
    mutate(data)
    with pytest.raises(ValueError, match=message):
        Catalog(data)


# ── software catalogue ─────────────────────────────────────────────────────
@pytest.mark.parametrize("name, publisher, product, vendor, category", [
    ("Google Chrome", "Google LLC", "Google Chrome", "Google", "Browser"),
    ("AnyDesk", "philandro Software GmbH", "AnyDesk", "AnyDesk Software", "Remote access"),
    ("Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.38.33130", "Microsoft Corporation",
     "Microsoft Visual C++ Redistributable", "Microsoft", "Runtime & framework"),
    ("Dell Command | Update for Windows Universal", "Dell Inc.", "Dell system utilities", "Dell", "System component"),
    ("PyCharm Community Edition 2024.1", "JetBrains s.r.o.", "JetBrains PyCharm", "JetBrains", "Development"),
    ("qBittorrent 4.6.3", "The qBittorrent project", "qBittorrent", "The qBittorrent project", "File sharing & P2P"),
    ("Some Internal App 2.1", "Contoso Pty Ltd.", "Some Internal App", "Contoso", None),
])
def test_software_classification(name, publisher, product, vendor, category):
    c = classify_software(name, publisher)
    assert (c.product, c.publisher, c.category) == (product, vendor, category)


# ── device lifecycle through ingest ────────────────────────────────────────
def _report(host, os_name, os_version, os_build, software=(), serial=None):
    return InventoryReport.model_validate({
        "hostname": host, "os_name": os_name, "os_version": os_version, "os_build": os_build,
        "hardware": {"serial_number": serial or f"SN-{host}"},
        "software": [{"name": n, "version": v, "publisher": p} for n, v, p in software],
    })


async def _rows(db, device_id):
    rows = (await db.execute(select(DeviceLifecycle).where(DeviceLifecycle.device_id == device_id))).scalars().all()
    return {(r.kind, r.title) for r in rows}


async def test_ingest_builds_lifecycle_rows_and_categories(db_session):
    r = await InventoryService.ingest(db_session, "agent", _report(
        "PC-1", "Microsoft Windows 10 Pro", "10.0.19045", "19045.4529",
        software=[("Microsoft Office Professional Plus 2016", "16.0.4266.1001", "Microsoft Corporation"),
                  ("Microsoft Office Proofing Tools 2016 - English", "16.0", "Microsoft Corporation"),
                  ("Python 3.12.4 (64-bit)", "3.12.4150.0", "Python Software Foundation"),
                  ("TeamViewer", "15.50", "TeamViewer")]))
    await db_session.commit()
    assert await _rows(db_session, r["device_id"]) == {
        ("os", "Windows 10 22H2"), ("software", "Microsoft Office 2016"), ("software", "Python 3.12")}
    sw = {s.name: (s.normalized_name, s.vendor, s.category)
          for s in (await db_session.execute(select(InstalledSoftware))).scalars()}
    assert sw["TeamViewer"] == ("TeamViewer", "TeamViewer", "Remote access")
    assert sw["Microsoft Office Professional Plus 2016"] == ("Microsoft Office", "Microsoft", "Office & productivity")

    # Upgrading the OS and removing Office is reflected on the next report
    await InventoryService.ingest(db_session, "agent", _report(
        "PC-1", "Microsoft Windows 11 Enterprise", "10.0.26100", "26100.1",
        software=[("Python 3.12.4 (64-bit)", "3.12.4150.0", "Python Software Foundation")]))
    await db_session.commit()
    assert await _rows(db_session, r["device_id"]) == {
        ("os", "Windows 11 24H2 (Enterprise/Education)"), ("software", "Python 3.12")}


async def test_refresh_all_covers_directory_only_devices_and_reclassifies(db_session):
    # A computer only Active Directory knows: OS strings come from its raw record
    await Correlator.process_batch(db_session, "ad", [
        make_raw(source_uid="ad-1", hostname="OLD-SRV", fqdn=None, os_name="Windows Server 2012 R2 Standard",
                 os_version="6.3 (9600)")])
    r = await InventoryService.ingest(db_session, "agent", _report(
        "PC-2", "Microsoft Windows 11 Pro", "10.0.22631", "22631.1", software=[("AnyDesk", "8.0", "philandro")]))
    await db_session.commit()
    # Simulate rows written before the software catalogue existed
    sw = (await db_session.execute(select(InstalledSoftware))).scalars().one()
    sw.normalized_name, sw.vendor, sw.category = "AnyDesk", None, None
    await db_session.commit()

    result = await LifecycleService.refresh_all(db_session)
    assert result["devices_with_os"] == 2 and result["software_reclassified"] == 1
    titles = {t for _, t in (await db_session.execute(select(DeviceLifecycle.kind, DeviceLifecycle.title))).all()}
    assert titles == {"Windows Server 2012 R2", "Windows 11 23H2 (Home/Pro)"}
    await db_session.refresh(sw)
    assert sw.category == "Remote access"
    assert await _rows(db_session, r["device_id"]) == {("os", "Windows 11 23H2 (Home/Pro)")}


# ── API: summary, device card, drill-down, catalogue upload ────────────────
def _relative_catalogue(published: str, version: str) -> dict:
    """A catalogue whose Windows 10 22H2 dates are relative to today."""
    data = _bundled_json()
    data["version"], data["published"] = version, published
    win10 = next(p for p in data["products"] if p["id"] == "windows-10")
    cycle = next(c for c in win10["cycles"] if c["cycle"] == "22H2")
    cycle["eol"] = (TODAY + timedelta(days=30)).isoformat()
    return data


async def _seed(api):
    async with api.session_factory() as s:
        a = await InventoryService.ingest(s, "agent", _report(
            "WIN10-PC", "Microsoft Windows 10 Pro", "10.0.19045", "19045.1", serial="SER-A1",
            software=[("Microsoft SQL Server 2014 (64-bit)", "12.0", "Microsoft Corporation")]))
        b = await InventoryService.ingest(s, "agent", _report(
            "SRV-25", "Microsoft Windows Server 2025 Standard", "10.0.26100", "26100.1", serial="SER-B2"))
        s.add(Asset(name="Win10 laptop", asset_tag="AST-1", category="hardware", device_id=a["device_id"],
                    serial_number="ser-a1", warranty_end=TODAY - timedelta(days=10)))
        await s.commit()
    return a["device_id"], b["device_id"]


async def test_summary_device_card_and_drilldown(api):
    win10, srv = await _seed(api)
    data = (await api.get("/api/lifecycle/summary")).json()["data"]
    c = data["counts"]
    assert (c["active_devices"], c["os_identified"], c["os_unsupported"], c["software_unsupported_devices"]) == (2, 2, 1, 1)
    assert c["warranty_expired"] == 1
    assert [(r["title"], r["status"], r["devices"]) for r in data["os"]] == [
        ("Windows 10 22H2", "unsupported", 1), ("Windows Server 2025", "supported", 1)]
    assert [r["title"] for r in data["software"]] == ["Microsoft SQL Server 2014"]
    assert data["catalog"]["origin"] == "bundled"

    card = (await api.get(f"/api/devices/{win10}/lifecycle")).json()["data"]
    assert (card["os"]["title"], card["os"]["status"]) == ("Windows 10 22H2", "unsupported")
    assert [s["title"] for s in card["software"]] == ["Microsoft SQL Server 2014"]
    assert (card["warranty"]["asset_tag"], card["warranty"]["status"]) == ("AST-1", "expired")
    assert (await api.get(f"/api/devices/{srv}/lifecycle")).json()["data"]["warranty"] is None

    rows = (await api.get("/api/lifecycle/devices", params={
        "kind": "os", "product_id": "windows-10", "cycle": "22H2"})).json()["data"]
    assert [r["hostname"] for r in rows] == ["WIN10-PC"]

    health = (await api.get("/api/dashboard/endpoint-health")).json()["data"]
    assert health["counts"]["unsupported_os"] == 1
    listed = (await api.get("/api/devices", params={"health": "unsupported_os"})).json()["data"]
    assert [d["hostname"] for d in listed["items"]] == ["WIN10-PC"]


async def test_catalogue_upload(api):
    win10, _ = await _seed(api)

    def upload(data):
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        return api.post("/api/lifecycle/catalog", files={"file": ("eol.json", io.BytesIO(body), "application/json")})

    r = await upload(_relative_catalogue((TODAY + timedelta(days=1)).isoformat(), "9999.1"))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["origin"] == "uploaded" and r.json()["data"]["version"] == "9999.1"
    card = (await api.get(f"/api/devices/{win10}/lifecycle")).json()["data"]
    assert (card["os"]["status"], card["os"]["days_left"]) == ("ending_soon", 30)

    # An older upload is kept on file but the newer catalogue stays in use
    r = await upload(_relative_catalogue("2020-01-01", "2020.1"))
    assert r.status_code == 200 and "stays in use" in r.json()["message"]
    assert (await api.get("/api/lifecycle/catalog")).json()["data"]["version"] == "9999.1"

    bad = copy.deepcopy(_bundled_json())
    bad["products"][0]["cycles"][0]["eol"] = "soon"
    r = await upload(bad)
    assert r.status_code == 400 and "YYYY-MM-DD" in r.json()["detail"]
    assert (await upload(b"not json")).status_code == 400


async def test_catalogue_admin_only(api):
    async with api.session_factory() as s:
        s.add(User(username="viewer", email="v@test.local", hashed_password=get_password_hash("x"), role="viewer"))
        await s.commit()
    headers = {"Authorization": f"Bearer {create_access_token('viewer')}"}
    r = await api.post("/api/lifecycle/refresh", headers=headers)
    assert r.status_code == 403
    r = await api.post("/api/lifecycle/warranty-import", headers=headers,
                       files={"file": ("w.csv", io.BytesIO(b"Serial,End Date\nX,2030-01-01\n"), "text/csv")})
    assert r.status_code == 403
    assert (await api.post("/api/lifecycle/refresh")).status_code == 200


# ── warranty import ────────────────────────────────────────────────────────
def test_parse_date_orders():
    assert parse_date("03/04/2027", "dmy") == date(2027, 4, 3)
    assert parse_date("03/04/2027", "mdy") == date(2027, 3, 4)
    assert parse_date("2027-04-03T00:00:00") == date(2027, 4, 3)
    assert parse_date("3 Apr 2027") == parse_date("April 3, 2027") == date(2027, 4, 3)


async def test_warranty_import(api):
    win10, _ = await _seed(api)
    async with api.session_factory() as s:
        s.add(Asset(name="Spare", asset_tag="AST-9", category="hardware", serial_number="SPARE-9",
                    purchase_date=date(2020, 1, 1)))
        await s.commit()
    csv = (
        "Service Tag,Ship Date,Warranty End Date,Service Level\n"
        "SER-A1,15/03/2023,14/03/2026,Basic\n"
        "ser-a1,15/03/2023,14/03/2028,ProSupport\n"         # several lines per serial: the latest end wins
        "SPARE-9,01/02/2021,01/02/2027,Basic\n"             # purchase date already set: kept
        "SER-B2,01/01/2025,01/01/2030,Basic\n"              # a device without an asset
        "NOPE-1,01/01/2025,01/01/2030,Basic\n"
        "BAD-1,01/01/2025,31/31/2030,Basic\n"
    )
    r = await api.post("/api/lifecycle/warranty-import", data={"date_order": "dmy"},
                       files={"file": ("dell.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert (d["updated"], d["unchanged"], d["device_only_count"], d["not_found"]) == (2, 0, 1, ["NOPE-1"])
    assert d["device_only"][0]["hostname"] == "SRV-25"
    assert len(d["errors"]) == 1 and d["errors"][0]["row"] == 7
    async with api.session_factory() as s:
        assets = {a.asset_tag: a for a in (await s.execute(select(Asset))).scalars()}
    assert (assets["AST-1"].warranty_end, assets["AST-1"].purchase_date) == (date(2028, 3, 14), date(2023, 3, 15))
    assert (assets["AST-9"].warranty_end, assets["AST-9"].purchase_date) == (date(2027, 2, 1), date(2020, 1, 1))

    # Re-importing the same file changes nothing
    r = await api.post("/api/lifecycle/warranty-import", data={"date_order": "dmy"},
                       files={"file": ("dell.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert (r.json()["data"]["updated"], r.json()["data"]["unchanged"]) == (0, 2)

    r = await api.post("/api/lifecycle/warranty-import",
                       files={"file": ("x.csv", io.BytesIO(b"Name,Owner\nA,B\n"), "text/csv")})
    assert r.status_code == 400 and "serial number" in r.json()["detail"]


# ── reports and alerts ─────────────────────────────────────────────────────
async def test_lifecycle_reports(api):
    await _seed(api)
    async with api.session_factory() as s:
        await InventoryService.ingest(s, "agent", _report(
            "PC-GAMES", "Microsoft Windows Server 2025 Standard", "10.0.26100", "26100.1",
            software=[("Steam", "2.10", "Valve Corporation"), ("AnyDesk", "8.0", "philandro Software GmbH"),
                      ("Google Chrome", "120.0", "Google LLC")]))
        await s.commit()

    async def run(report_id):
        r = await api.post("/api/reports/run", json={"definition": BY_ID[f"builtin:{report_id}"]["definition"]})
        assert r.status_code == 200, r.text
        return r.json()["data"]

    assert [r["hostname"] for r in (await run("os-unsupported"))["rows"]] == ["WIN10-PC"]
    assert [(r["hostname"], r["title"]) for r in (await run("software-unsupported"))["rows"]] == [
        ("WIN10-PC", "Microsoft SQL Server 2014")]
    unwanted = (await run("unwanted-software"))["rows"]
    assert sorted((r["name"], r["category"]) for r in unwanted) == [("AnyDesk", "Remote access"), ("Steam", "Games")]
    by_cat = {g["value"]: g["count"] for g in (await run("software-by-category"))["groups"]}
    assert by_cat["Browser"] == 1 and by_cat["Database"] == 1
    assert [r["hostname"] for r in (await run("warranty-expired-devices"))["rows"]] == ["WIN10-PC"]
    releases = {g["value"] for g in (await run("os-releases"))["groups"]}
    assert "Windows 10 22H2" in releases


async def test_os_end_of_support_alert(db_session):
    eol_catalog.use(Catalog(_relative_catalogue(TODAY.isoformat(), "test.1")))
    await InventoryService.ingest(db_session, "agent", _report("PC-A", "Microsoft Windows 10 Pro", "10.0.19045", "19045.1"))
    await InventoryService.ingest(db_session, "agent", _report("PC-B", "Microsoft Windows 7 Professional", "6.1.7601", "7601"))
    await db_session.commit()
    items = await NotificationService._os_eol_items(db_session, 60)
    assert items[0].startswith("- Windows 10 22H2: support ends") and "30d left" in items[0] and "1 device" in items[0]
    assert "1 device already run" in items[1]
    assert await NotificationService._os_eol_items(db_session, 10) == []
