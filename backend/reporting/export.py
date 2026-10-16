"""
CSV / Excel export of report results.

Spreadsheet formula injection: hostnames, software names and the like arrive
from agent reports, which a user of the reported machine can influence. Text
that starts with = + - @ (or tab / CR) would be evaluated as a formula when the
file is opened, so it is written with a leading apostrophe. Numbers and dates
are written as real values and are unaffected.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from typing import Any, List, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    if isinstance(value, (list, tuple)):
        return safe_text(", ".join(str(v) for v in value))
    return value


def filename(name: str, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()[:60] or "report"
    return f"{slug}-{date.today().isoformat()}.{ext}"


def to_csv(header: Sequence[Tuple[str, str]], rows: List[List[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in header])
    for row in rows:
        w.writerow(["" if v is None else safe_text(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")      # BOM: Excel opens UTF-8 correctly


def _cell_value(v: Any, type_: str) -> Any:
    if v is None:
        return None
    if type_ == "date" and isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return v
    if type_ == "datetime" and isinstance(v, str):
        try:     # Excel has no time zones: write UTC, naive
            return datetime.fromisoformat(v).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return v
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return safe_text(v)


def to_xlsx(title: str, header: Sequence[Tuple[str, str]], types: Sequence[str], rows: List[List[Any]],
            summary: List[Tuple[str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.append([label for _, label in header])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="16A34A")
    for row in rows:
        ws.append([_cell_value(v, t) for v, t in zip(row, types)])
    for i, t in enumerate(types, start=1):
        letter = get_column_letter(i)
        if t == "date":
            for cell in ws[letter][1:]:
                cell.number_format = "yyyy-mm-dd"
        elif t == "datetime":
            for cell in ws[letter][1:]:
                cell.number_format = "yyyy-mm-dd hh:mm"
        width = max([len(str(header[i - 1][1]))] + [len(str(r[i - 1])) for r in rows[:500] if r[i - 1] is not None])
        ws.column_dimensions[letter].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions

    info = wb.create_sheet("About")
    info.append(["Report", safe_text(title)])
    info.append(["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
    info.append(["Rows", len(rows)])
    for k, v in summary:
        info.append([k, safe_text(v)])
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 80
    for row in info.iter_rows(max_col=1):
        row[0].font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
