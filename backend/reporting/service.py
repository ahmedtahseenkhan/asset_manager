"""Report files and scheduled delivery."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.notification import NotificationLog
from backend.models.saved_report import SavedReport
from backend.reporting import export
from backend.reporting.engine import OPERATOR_LABELS, ReportDefinition, columns_for, export_rows
from backend.reporting.entities import ENTITIES

logger = logging.getLogger(__name__)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"


def describe(defn: ReportDefinition) -> List[Tuple[str, str]]:
    """Human-readable summary: what the report shows and how it filters."""
    e = ENTITIES[defn.entity]
    out = [("Data", e.label)]
    parts = []
    for f in defn.filters:
        field = e.fields.get(f.field)
        label = field.label if field else f.field
        value = "" if f.value in (None, "") else f" {f.value}"
        parts.append(f"{label} {OPERATOR_LABELS.get(f.op, f.op)}{value}")
    if parts:
        joiner = " AND " if defn.match == "all" else " OR "
        out.append(("Filters", joiner.join(parts)))
    if defn.search:
        out.append(("Search", defn.search))
    if defn.group_by:
        out.append(("Grouped by", e.fields[defn.group_by].label))
    return out


async def build_file(db: AsyncSession, name: str, defn: ReportDefinition, fmt: str) -> Tuple[str, bytes, str, int]:
    """(filename, content, mime, row count)."""
    header, rows = await export_rows(db, defn)
    if fmt == "csv":
        return export.filename(name, "csv"), export.to_csv(header, rows), CSV_MIME, len(rows)
    if defn.group_by:
        types = [ENTITIES[defn.entity].fields[defn.group_by].type, "number"]
    else:
        types = [f.type for f in columns_for(defn)]
    content = export.to_xlsx(name, header, types, rows, describe(defn))
    return export.filename(name, "xlsx"), content, XLSX_MIME, len(rows)


async def send_report(db: AsyncSession, report: SavedReport, recipients: Optional[List[str]] = None) -> str:
    """Email a saved report as an attachment; records the outcome. Returns a status line."""
    from backend.services.notification_service import NotificationService

    to = recipients if recipients is not None else list(report.recipients or [])
    defn = ReportDefinition.model_validate(report.definition)
    subject = f"[IT Asset Manager] {report.name}"
    try:
        fname, content, mime, count = await build_file(db, report.name, defn, report.export_format or "xlsx")
        body = (f"{report.name}\n"
                + "".join(f"{k}: {v}\n" for k, v in describe(defn))
                + f"Rows: {count}\nGenerated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n"
                + "The full report is attached.\n\n"
                  "This is an automated report from your on-premises IT Asset Manager.")
        await NotificationService.send_email(db, subject, body, to, attachments=[(fname, content, mime)])
        status, error = "sent", None
        line = f"sent to {len(to)} recipient(s), {count} row(s)"
    except Exception as exc:          # record and report failures; never crash the scheduler
        logger.error("Scheduled report %s failed: %s", report.id, exc)
        status, error, count = "failed", str(exc), 0
        line = f"failed: {exc}"
    report.last_sent_at = datetime.now(timezone.utc)
    report.last_status = line[:255]
    db.add(NotificationLog(rule_type="scheduled_report", subject=subject, recipients=to,
                           item_count=count, status=status, error=error))
    await db.commit()
    return line
