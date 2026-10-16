"""
Lifecycle: end-of-life status per device (OS and installed software) and the
software catalogue classification, kept in step with inventory and with the
catalogues in use.

- After each inventory report, the device's rows are rebuilt (refresh_device).
- At startup, daily, and after a catalogue upload, everything is recomputed
  (refresh_all), which also covers devices that only directory/EDR connectors
  know (their OS strings are read from the source's raw record).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import bindparam, delete, distinct, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.lifecycle import eol as eol_catalog
from backend.lifecycle.eol import ENDING_SOON_DAYS, Catalog, EolMatch, status
from backend.models.asset import Asset
from backend.models.device import Device
from backend.models.device_source import DeviceSource
from backend.models.inventory import DeviceInventory
from backend.models.lifecycle import DeviceLifecycle, LifecycleCatalog
from backend.models.software import InstalledSoftware
from backend.services.software_normalizer import classify_software

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_ADVISORY_KEY = 0x11FEC7C1        # one full refresh at a time across API containers
WARRANTY_SOON_DAYS = 90


def _chunks(items: List, size: int = 500) -> Iterable[List]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _os_detail(name: Optional[str], version: Optional[str], build: Optional[str]) -> str:
    """"Microsoft Windows 11 Pro 10.0.22631 (build 22631.4317)", "macOS 26.1 (build 25B78)"."""
    text = " ".join(str(v) for v in (name, version) if v)
    return (f"{text} (build {build})" if build and build != version else text)[:500]


def _match_os(cat: Catalog, inv: Optional[Tuple], raws: List[Tuple]) -> Optional[Tuple[EolMatch, str]]:
    """The inventory's OS strings first (agent/scan), then each source's raw
    record (AD's operatingSystem + "10.0 (19045)", Defender, …)."""
    if inv and inv[0]:
        m = cat.match_os(*inv)
        if m:
            return m, _os_detail(*inv)
    for name, version in raws:
        m = cat.match_os(name, version)
        if m:
            return m, _os_detail(name, version, None)
    return None


_RAW_OS = (DeviceSource.raw_data["os_name"].as_string(), DeviceSource.raw_data["os_version"].as_string())


def _row(device_id: int, m: EolMatch, detail: str, version: str) -> Dict[str, Any]:
    return {"device_id": device_id, "kind": m.kind, "product_id": m.product_id, "product": m.product[:128],
            "cycle": m.cycle, "title": m.title, "eol": m.eol, "support_end": m.support_end,
            "extended": m.extended, "detail": detail[:500], "catalog_version": version}


class LifecycleService:
    # ── catalogue ───────────────────────────────────────────────────────────
    @staticmethod
    async def load_catalog(db: AsyncSession) -> Tuple[Catalog, str]:
        """Put the newest of the bundled and the last uploaded catalogue in use."""
        best, origin = Catalog.bundled(), "bundled"
        row = (await db.execute(select(LifecycleCatalog).order_by(
            LifecycleCatalog.published.desc(), LifecycleCatalog.id.desc()).limit(1))).scalars().first()
        if row is not None:
            try:
                uploaded = Catalog(row.content)
                if uploaded.sort_key >= best.sort_key:
                    best, origin = uploaded, "uploaded"
            except ValueError as exc:
                logger.warning("Ignoring uploaded end-of-life catalogue %s: %s", row.version, exc)
        eol_catalog.use(best)
        return best, origin

    @staticmethod
    async def catalog_info(db: AsyncSession) -> Dict[str, Any]:
        cat = eol_catalog.current()
        bundled = Catalog.bundled()
        last = (await db.execute(select(LifecycleCatalog).order_by(LifecycleCatalog.id.desc()).limit(1))
                ).scalars().first()
        return {
            "version": cat.version, "published": cat.published.isoformat(),
            "origin": "bundled" if cat.sort_key == bundled.sort_key else "uploaded",
            "bundled_version": bundled.version,
            "last_upload": ({"version": last.version, "published": last.published.isoformat(),
                             "uploaded_at": last.uploaded_at} if last else None),
            "products": len(cat.products),
        }

    @staticmethod
    async def upload_catalog(db: AsyncSession, data: Dict[str, Any], user_id: Optional[int]) -> Catalog:
        cat = Catalog(data)                       # raises ValueError with the problem
        db.add(LifecycleCatalog(version=cat.version, published=cat.published, content=data, uploaded_by=user_id))
        await db.flush()
        return cat

    # ── per device ──────────────────────────────────────────────────────────
    @staticmethod
    async def refresh_device(db: AsyncSession, device_id: int) -> None:
        """Rebuild one device's lifecycle rows. Flushes; the caller commits."""
        cat = eol_catalog.current()
        inv = (await db.execute(select(DeviceInventory.os_name, DeviceInventory.os_version, DeviceInventory.os_build)
                                .where(DeviceInventory.device_id == device_id))).first()
        raws = (await db.execute(select(*_RAW_OS).where(DeviceSource.device_id == device_id))).all()
        rows: Dict[tuple, Dict[str, Any]] = {}
        hit = _match_os(cat, tuple(inv) if inv else None, [tuple(r) for r in raws])
        if hit:
            m, detail = hit
            rows[("os", m.product_id, m.cycle)] = _row(device_id, m, detail, cat.version)
        titles = (await db.execute(select(InstalledSoftware.name, InstalledSoftware.version)
                                   .where(InstalledSoftware.device_id == device_id))).all()
        for name, version in sorted(titles, key=lambda t: (t[0], t[1] or "")):
            m = cat.match_software(name, version)
            if m:
                rows.setdefault(("software", m.product_id, m.cycle),
                                _row(device_id, m, f"{name} {version or ''}".strip(), cat.version))
        await db.execute(delete(DeviceLifecycle).where(DeviceLifecycle.device_id == device_id))
        if rows:
            await db.execute(insert(DeviceLifecycle), list(rows.values()))

    # ── everything ──────────────────────────────────────────────────────────
    @staticmethod
    async def refresh_all(db: AsyncSession) -> Dict[str, Any]:
        """Recompute software classes and every device's lifecycle rows. Commits."""
        async with _lock:
            if db.bind.dialect.name == "postgresql":
                if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _ADVISORY_KEY}):
                    return {"skipped": "another refresh is running"}
            reclassified = await LifecycleService._reclassify_software(db)
            cat = eol_catalog.current()
            rows: Dict[tuple, Dict[str, Any]] = {}

            # OS: inventory first, then the raw records of devices it didn't identify
            os_found = set()
            for did, n, v, b in (await db.execute(select(
                    DeviceInventory.device_id, DeviceInventory.os_name, DeviceInventory.os_version,
                    DeviceInventory.os_build))).all():
                hit = _match_os(cat, (n, v, b), [])
                if hit:
                    m, detail = hit
                    rows[(did, "os", m.product_id, m.cycle)] = _row(did, m, detail, cat.version)
                    os_found.add(did)
            raw_q = select(DeviceSource.device_id, *_RAW_OS).where(_RAW_OS[0].isnot(None))
            for did, name, version in (await db.execute(raw_q)).all():
                if did in os_found:
                    continue
                hit = _match_os(cat, None, [(name, version)])
                if hit:
                    m, detail = hit
                    rows[(did, "os", m.product_id, m.cycle)] = _row(did, m, detail, cat.version)
                    os_found.add(did)

            # Software: match each distinct title once, then find who has it
            matched: Dict[tuple, EolMatch] = {}
            for name, version in (await db.execute(
                    select(InstalledSoftware.name, InstalledSoftware.version).distinct())).all():
                m = cat.match_software(name, version)
                if m:
                    matched[(name, version)] = m
            names = sorted({n for n, _ in matched})
            for chunk in _chunks(names):
                for did, name, version in (await db.execute(
                        select(InstalledSoftware.device_id, InstalledSoftware.name, InstalledSoftware.version)
                        .where(InstalledSoftware.name.in_(chunk))
                        .order_by(InstalledSoftware.name, InstalledSoftware.version))).all():
                    m = matched.get((name, version))
                    if m:
                        rows.setdefault((did, "software", m.product_id, m.cycle),
                                        _row(did, m, f"{name} {version or ''}".strip(), cat.version))

            await db.execute(delete(DeviceLifecycle))
            values = list(rows.values())
            for chunk in _chunks(values, 1000):
                await db.execute(insert(DeviceLifecycle), chunk)
            await db.commit()
            result = {"catalog": cat.version, "devices_with_os": len(os_found),
                      "items": len(values), "software_reclassified": reclassified}
            logger.info("Lifecycle refresh: %s", result)
            return result

    @staticmethod
    async def _reclassify_software(db: AsyncSession) -> int:
        """Apply the software catalogue to every distinct (title, publisher)."""
        groups = (await db.execute(select(
            InstalledSoftware.name, InstalledSoftware.publisher, InstalledSoftware.normalized_name,
            InstalledSoftware.vendor, InstalledSoftware.category).distinct())).all()
        with_pub, without_pub = [], []
        for name, publisher, product, vendor, category in groups:
            c = classify_software(name, publisher)
            if (c.product, c.publisher, c.category) != (product, vendor, category):
                params = {"n": name, "p": publisher, "product": c.product, "vendor": c.publisher, "category": c.category}
                (with_pub if publisher is not None else without_pub).append(params)
        values = {"normalized_name": bindparam("product"), "vendor": bindparam("vendor"),
                  "category": bindparam("category")}
        conn = await db.connection()
        if with_pub:
            await conn.execute(update(InstalledSoftware).where(
                InstalledSoftware.name == bindparam("n"), InstalledSoftware.publisher == bindparam("p")
            ).values(**values).execution_options(synchronize_session=False), with_pub)
        if without_pub:
            await conn.execute(update(InstalledSoftware).where(
                InstalledSoftware.name == bindparam("n"), InstalledSoftware.publisher.is_(None)
            ).values(**values).execution_options(synchronize_session=False),
                [{k: v for k, v in p.items() if k != "p"} for p in without_pub])
        return len(with_pub) + len(without_pub)

    # ── views ───────────────────────────────────────────────────────────────
    @staticmethod
    def _view(r: DeviceLifecycle, today: date) -> Dict[str, Any]:
        return {"kind": r.kind, "product_id": r.product_id, "product": r.product, "cycle": r.cycle,
                "title": r.title, "eol": r.eol, "support_end": r.support_end, "extended": r.extended,
                "detail": r.detail, "status": status(r.eol, today),
                "days_left": (r.eol - today).days if r.eol else None}

    @staticmethod
    async def device(db: AsyncSession, device_id: int) -> Dict[str, Any]:
        today = date.today()
        rows = (await db.execute(select(DeviceLifecycle).where(DeviceLifecycle.device_id == device_id)
                                 .order_by(DeviceLifecycle.eol.asc().nullslast(), DeviceLifecycle.title))).scalars().all()
        os_row = next((r for r in rows if r.kind == "os"), None)
        asset = (await db.execute(select(Asset).where(Asset.device_id == device_id).order_by(Asset.id).limit(1))
                 ).scalars().first()
        warranty = None
        if asset is not None:
            end = asset.warranty_end
            warranty = {"asset_id": asset.id, "asset_tag": asset.asset_tag, "warranty_end": end,
                        "purchase_date": asset.purchase_date,
                        "status": None if end is None else ("expired" if end < today else
                                                           "ending_soon" if (end - today).days <= WARRANTY_SOON_DAYS
                                                           else "active")}
        return {"os": LifecycleService._view(os_row, today) if os_row else None,
                "software": [LifecycleService._view(r, today) for r in rows if r.kind == "software"],
                "warranty": warranty}

    @staticmethod
    async def summary(db: AsyncSession) -> Dict[str, Any]:
        today = date.today()
        soon = today + timedelta(days=ENDING_SOON_DAYS)
        active = Device.status == "active"
        L = DeviceLifecycle

        async def devices(*conds) -> int:
            return (await db.scalar(select(func.count(distinct(L.device_id)))
                                    .join(Device, Device.id == L.device_id).where(active, *conds))) or 0

        def grouped(kind: str):
            return (select(L.product_id, L.product, L.cycle, L.title, L.eol, L.extended,
                           func.count(distinct(L.device_id)).label("devices"))
                    .join(Device, Device.id == L.device_id).where(active, L.kind == kind)
                    .group_by(L.product_id, L.product, L.cycle, L.title, L.eol, L.extended))

        def view(r) -> Dict[str, Any]:
            return {"product_id": r.product_id, "product": r.product, "cycle": r.cycle, "title": r.title,
                    "eol": r.eol, "extended": r.extended, "devices": r.devices, "status": status(r.eol, today),
                    "days_left": (r.eol - today).days if r.eol else None}

        os_rows = [view(r) for r in (await db.execute(grouped("os"))).all()]
        sw_rows = [view(r) for r in (await db.execute(
            grouped("software").where(L.eol.isnot(None), L.eol <= soon))).all()]
        order = {"unsupported": 0, "ending_soon": 1, "supported": 2}
        for rows in (os_rows, sw_rows):
            rows.sort(key=lambda r: (order[r["status"]], r["eol"] or date.max, r["title"]))

        active_devices = (await db.scalar(select(func.count(Device.id)).where(active))) or 0
        identified = await devices(L.kind == "os")
        live = Asset.lifecycle_state != "retired"
        hardware = Asset.category == "hardware"
        return {
            "counts": {
                "active_devices": active_devices,
                "os_identified": identified,
                "os_unidentified": max(active_devices - identified, 0),
                "os_unsupported": await devices(L.kind == "os", L.eol < today),
                "os_ending_soon": await devices(L.kind == "os", L.eol >= today, L.eol <= soon),
                "software_unsupported_devices": await devices(L.kind == "software", L.eol < today),
                "warranty_expired": (await db.scalar(select(func.count(Asset.id)).where(
                    live, Asset.warranty_end < today))) or 0,
                "warranty_ending_soon": (await db.scalar(select(func.count(Asset.id)).where(
                    live, Asset.warranty_end >= today,
                    Asset.warranty_end <= today + timedelta(days=WARRANTY_SOON_DAYS)))) or 0,
                "warranty_unknown": (await db.scalar(select(func.count(Asset.id)).where(
                    live, hardware, Asset.warranty_end.is_(None)))) or 0,
            },
            "ending_soon_days": ENDING_SOON_DAYS,
            "warranty_soon_days": WARRANTY_SOON_DAYS,
            "os": os_rows,
            "software": sw_rows,
            "catalog": await LifecycleService.catalog_info(db),
        }

    @staticmethod
    async def devices_for(db: AsyncSession, kind: str, product_id: str, cycle: str,
                          limit: int = 1000) -> List[Dict[str, Any]]:
        L = DeviceLifecycle
        rows = (await db.execute(
            select(L.device_id, Device.hostname, Device.last_seen, L.title, L.detail, L.eol)
            .join(Device, Device.id == L.device_id)
            .where(Device.status == "active", L.kind == kind, L.product_id == product_id, L.cycle == cycle)
            .order_by(Device.hostname).limit(limit))).all()
        return [{"device_id": r.device_id, "hostname": r.hostname, "last_seen": r.last_seen,
                 "title": r.title, "detail": r.detail, "eol": r.eol} for r in rows]


async def lifecycle_startup(session_factory) -> None:
    """Load the catalogue in use and bring every device up to date (background)."""
    try:
        async with session_factory() as db:
            await LifecycleService.load_catalog(db)
            await LifecycleService.refresh_all(db)
    except Exception:            # never take the API down over this
        logger.exception("Lifecycle refresh at startup failed")
