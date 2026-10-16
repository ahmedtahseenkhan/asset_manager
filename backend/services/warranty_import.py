"""
Warranty dates from a CSV: an export from Dell TechDirect, Lenovo, HP or a
reseller, or a sheet kept by hand. Works offline.

Rows are matched to assets by serial number (or asset tag). Vendor exports
often list several entitlements per serial; the latest end date wins and the
earliest start date is used as the purchase date when the asset has none.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.asset import Asset
from backend.models.device import Device

MAX_ROWS = 50_000
DATE_ORDERS = ("dmy", "mdy")

_HEADERS = {
    "serial": {"serial", "serial number", "serialnumber", "serial no", "service tag", "servicetag", "sn",
               "asset serial", "machine serial", "serial #"},
    "asset_tag": {"asset tag", "assettag", "tag"},
    "warranty_end": {"warranty end", "warranty end date", "warranty expiration", "warranty expiration date",
                     "warranty expiry", "warranty expiry date", "warranty expires", "end date", "expiration date",
                     "expiry date", "coverage end", "coverage end date", "entitlement end date", "warranty_end"},
    "purchase_date": {"purchase date", "ship date", "shipped date", "start date", "warranty start",
                      "warranty start date", "coverage start date", "entitlement start date", "purchase_date"},
}
_MONTHS = ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y")


def _key(header: str) -> str:
    return re.sub(r"[\s_]+", " ", (header or "").strip().lower())


def _columns(headers: List[str]) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for h in headers:
        for field, names in _HEADERS.items():
            if _key(h) in names and field not in found:
                found[field] = h
    return found


def parse_date(value: str, order: str = "dmy") -> date:
    """ISO dates and month names always; 14/10/2025-style per `order` (dmy|mdy)."""
    v = (value or "").strip()
    if not v:
        raise ValueError("empty")
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?$", v)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?: .*)?$", v)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        day, month = (a, b) if order == "dmy" else (b, a)
        return date(y, month, day)
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", v)
    for candidate in (cleaned, re.sub(r"\s*,\s*", " ", cleaned)):
        for fmt in _MONTHS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"{value!r} is not a date")


async def import_warranty_csv(db: AsyncSession, data: bytes, order: str = "dmy") -> Dict[str, Any]:
    if order not in DATE_ORDERS:
        raise ValueError(f"date_order must be one of {', '.join(DATE_ORDERS)}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    cols = _columns(reader.fieldnames or [])
    if "warranty_end" not in cols or not ({"serial", "asset_tag"} & set(cols)):
        raise ValueError("The CSV needs a serial number (or asset tag) column and a warranty end date column. "
                         "Recognised headers include 'Serial Number', 'Service Tag', 'Asset Tag', "
                         "'Warranty End Date', 'End Date' and 'Ship Date'.")

    # serial/tag -> (latest end, earliest start); several lines per serial are normal
    wanted: Dict[Tuple[str, str], List[Optional[date]]] = {}
    errors: List[Dict[str, Any]] = []
    for line, row in enumerate(reader, start=2):
        if line > MAX_ROWS + 1:
            raise ValueError(f"At most {MAX_ROWS:,} rows per file")
        ident = None
        for field in ("serial", "asset_tag"):
            value = (row.get(cols[field]) or "").strip() if field in cols else ""
            if value:
                ident = (field, value.upper())
                break
        if ident is None:
            continue
        try:
            end = parse_date(row.get(cols["warranty_end"]) or "", order)
            start = None
            if "purchase_date" in cols and (row.get(cols["purchase_date"]) or "").strip():
                start = parse_date(row[cols["purchase_date"]], order)
        except ValueError as exc:
            if len(errors) < 50:
                errors.append({"row": line, "message": f"{ident[1]}: {exc}"})
            continue
        cur = wanted.setdefault(ident, [None, None])
        cur[0] = end if cur[0] is None or end > cur[0] else cur[0]
        cur[1] = start if start and (cur[1] is None or start < cur[1]) else cur[1]

    updated = unchanged = 0
    matched = set()
    for field, column in (("serial", Asset.serial_number), ("asset_tag", Asset.asset_tag)):
        keys = [k for f, k in wanted if f == field]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            for asset in (await db.execute(select(Asset).where(func.upper(func.trim(column)).in_(chunk)))).scalars():
                key = (field, (getattr(asset, "serial_number" if field == "serial" else "asset_tag") or "").strip().upper())
                end, start = wanted[key]
                matched.add(key)
                changed = False
                if asset.warranty_end != end:
                    asset.warranty_end, changed = end, True
                if start and asset.purchase_date is None:
                    asset.purchase_date, changed = start, True
                updated += changed
                unchanged += not changed

    missing = [k for k in wanted if k not in matched]
    serials = [k for f, k in missing if f == "serial"]
    device_only: List[Dict[str, Any]] = []
    if serials:
        for i in range(0, len(serials), 500):
            rows = (await db.execute(
                select(Device.id, Device.hostname, Device.serial_number)
                .where(func.upper(Device.serial_number).in_(serials[i:i + 500])))).all()
            device_only += [{"serial": s, "device_id": d, "hostname": h} for d, h, s in rows]
    found_on_device = {d["serial"].upper() for d in device_only}
    not_found = [k for _, k in missing if k not in found_on_device]
    await db.flush()
    return {
        "rows": len(wanted), "updated": updated, "unchanged": unchanged,
        "device_only": device_only[:200], "device_only_count": len(device_only),
        "not_found": not_found[:200], "not_found_count": len(not_found),
        "errors": errors,
    }
