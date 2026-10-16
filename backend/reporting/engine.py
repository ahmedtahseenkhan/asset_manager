"""
Report engine: validates a ReportDefinition against the entity whitelist and
compiles it into a parameterised SQLAlchemy query.

    definition = {
      "entity": "devices",
      "columns": ["hostname", "os_name", "ram_gb"],
      "filters": [{"field": "ram_gb", "op": "lt", "value": 8},
                  {"field": "has_software", "op": "has_not", "value": "Chrome"}],
      "match": "all",                     # or "any"
      "group_by": null,                   # or a field key -> value + count rows
      "sort": "hostname", "sort_dir": "asc",
      "chart": "none"                     # none | bar | pie (grouped reports)
    }
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field as PydField, field_validator
from sqlalchemy import String, and_, cast, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from backend.reporting.entities import ENTITIES, Entity, Field

MAX_COLUMNS = 40
MAX_FILTERS = 25
MAX_PAGE_SIZE = 500
MAX_EXPORT_ROWS = 100_000

# Operators per field type; value kind each expects.
OPERATORS: Dict[str, Dict[str, str]] = {
    "string": {"eq": "text", "neq": "text", "contains": "text", "not_contains": "text",
               "starts_with": "text", "in": "list", "is_empty": "none", "is_not_empty": "none"},
    "list": {"contains": "text", "not_contains": "text", "is_empty": "none", "is_not_empty": "none"},
    "enum": {"eq": "choice", "neq": "choice", "in": "choices", "is_empty": "none", "is_not_empty": "none"},
    "number": {"eq": "number", "neq": "number", "lt": "number", "lte": "number", "gt": "number",
               "gte": "number", "is_empty": "none", "is_not_empty": "none"},
    "date": {"before": "date", "after": "date", "older_than_days": "days", "within_last_days": "days",
             "within_next_days": "days", "is_past": "none", "is_empty": "none", "is_not_empty": "none"},
    "bool": {"is_true": "none", "is_false": "none", "is_unknown": "none"},
    "relation": {"has": "text", "has_not": "text"},
}
OPERATORS["datetime"] = OPERATORS["date"]

OPERATOR_LABELS = {
    "eq": "is", "neq": "is not", "contains": "contains", "not_contains": "does not contain",
    "starts_with": "starts with", "in": "is any of", "is_empty": "is empty", "is_not_empty": "is not empty",
    "lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "before": "before", "after": "after",
    "older_than_days": "more than N days ago", "within_last_days": "in the last N days",
    "within_next_days": "in the next N days", "is_past": "is in the past", "is_true": "is yes",
    "is_false": "is no", "is_unknown": "is unknown", "has": "has", "has_not": "does not have",
}


class ReportError(ValueError):
    pass


class FilterSpec(BaseModel):
    field: str
    op: str
    value: Any = None


class ReportDefinition(BaseModel):
    entity: str
    columns: List[str] = PydField(default_factory=list)
    filters: List[FilterSpec] = PydField(default_factory=list)
    match: Literal["all", "any"] = "all"
    search: Optional[str] = PydField(default=None, max_length=200)   # free text, ANDed with filters
    group_by: Optional[str] = None
    sort: Optional[str] = None
    sort_dir: Literal["asc", "desc"] = "asc"
    chart: Literal["none", "bar", "pie"] = "none"

    @field_validator("columns")
    @classmethod
    def _cols(cls, v):
        if len(v) > MAX_COLUMNS:
            raise ValueError(f"at most {MAX_COLUMNS} columns")
        return v

    @field_validator("filters")
    @classmethod
    def _filters(cls, v):
        if len(v) > MAX_FILTERS:
            raise ValueError(f"at most {MAX_FILTERS} filters")
        return v


# ── validation helpers ──────────────────────────────────────────────────────
def _entity(defn: ReportDefinition) -> Entity:
    e = ENTITIES.get(defn.entity)
    if e is None:
        raise ReportError(f"Unknown report entity {defn.entity!r}")
    return e


def _field(e: Entity, key: str, *, selectable: bool = False) -> Field:
    f = e.fields.get(key)
    if f is None:
        raise ReportError(f"{e.label} has no field {key!r}")
    if selectable and (f.filter_only or f.expr is None):
        raise ReportError(f"{f.label} can only be used as a filter")
    return f


def _text(f: Field, value: Any) -> str:
    s = "" if value is None else str(value).strip()
    if not s:
        raise ReportError(f"{f.label}: enter a value")
    if len(s) > 500:
        raise ReportError(f"{f.label}: value too long")
    return s


def _number(f: Field, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ReportError(f"{f.label}: {value!r} is not a number")


def _days(f: Field, value: Any) -> int:
    n = _number(f, value)
    if n < 0 or n > 36500 or n != int(n):
        raise ReportError(f"{f.label}: days must be a whole number between 0 and 36500")
    return int(n)


def _list(f: Field, value: Any) -> List[str]:
    items = value if isinstance(value, list) else str(value or "").split(",")
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        raise ReportError(f"{f.label}: enter at least one value")
    if len(items) > 200:
        raise ReportError(f"{f.label}: at most 200 values")
    return items


def _date(f: Field, value: Any) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ReportError(f"{f.label}: {value!r} is not a date (YYYY-MM-DD)")


def _choice(f: Field, value: Any) -> str:
    v = _text(f, value)
    if f.choices and v not in f.choices:
        raise ReportError(f"{f.label}: must be one of {', '.join(f.choices)}")
    return v


def _bound(f: Field, d: date, end_of_day: bool = False):
    """Compare dates as dates, datetimes against a UTC instant."""
    if f.type == "datetime":
        return datetime.combine(d, time.max if end_of_day else time.min, tzinfo=timezone.utc)
    return d


def _condition(f: Field, op: str, value: Any):
    ops = OPERATORS[f.type]
    if op not in ops:
        raise ReportError(f"{f.label}: operator {op!r} doesn't apply to this field")
    col = f.expr
    today = date.today()

    if f.type == "relation":
        clause = f.relation(_text(f, value))
        return clause if op == "has" else not_(clause)
    if op == "is_empty":
        return or_(col.is_(None), cast(col, String) == "") if f.type in ("string", "enum") else col.is_(None)
    if op == "is_not_empty":
        return and_(col.isnot(None), cast(col, String) != "") if f.type in ("string", "enum") else col.isnot(None)

    if f.type == "bool":
        return {"is_true": col.is_(True), "is_false": col.is_(False), "is_unknown": col.is_(None)}[op]

    if f.type == "list":
        clause = cast(col, String).ilike(f"%{_text(f, value)}%")
        return clause if op == "contains" else or_(col.is_(None), not_(clause))

    if f.type == "string":
        if op == "in":
            return func.lower(col).in_([v.lower() for v in _list(f, value)])
        v = _text(f, value)
        return {
            "eq": func.lower(col) == v.lower(),
            "neq": or_(col.is_(None), func.lower(col) != v.lower()),
            "contains": col.ilike(f"%{v}%"),
            "not_contains": or_(col.is_(None), not_(col.ilike(f"%{v}%"))),
            "starts_with": col.ilike(f"{v}%"),
        }[op]

    if f.type == "enum":
        if op == "in":
            return col.in_([_choice(f, v) for v in _list(f, value)])
        v = _choice(f, value)
        return col == v if op == "eq" else or_(col.is_(None), col != v)

    if f.type == "number":
        n = _number(f, value)
        return {"eq": col == n, "neq": or_(col.is_(None), col != n), "lt": col < n, "lte": col <= n,
                "gt": col > n, "gte": col >= n}[op]

    # date / datetime
    if op == "is_past":
        return col < _bound(f, today)
    if op in ("before", "after"):
        d = _date(f, value)
        return col < _bound(f, d) if op == "before" else col > _bound(f, d, end_of_day=True)
    n = _days(f, value)
    if op == "older_than_days":
        return col < _bound(f, today - timedelta(days=n))
    if op == "within_last_days":
        return and_(col >= _bound(f, today - timedelta(days=n)), col <= _bound(f, today, end_of_day=True))
    return and_(col >= _bound(f, today), col <= _bound(f, today + timedelta(days=n), end_of_day=True))


# ── compilation ─────────────────────────────────────────────────────────────
def _from(e: Entity, q: Select) -> Select:
    q = q.select_from(e.base)
    for model, onclause in e.joins:
        q = q.outerjoin(model, onclause)
    return q


def _where(e: Entity, defn: ReportDefinition, q: Select) -> Select:
    conds = [_condition(_field(e, f.field), f.op, f.value) for f in defn.filters]
    if conds:
        q = q.where(and_(*conds) if defn.match == "all" else or_(*conds))
    term = (defn.search or "").strip()
    if term:
        q = q.where(or_(*(cast(f.expr, String).ilike(f"%{term}%") if f.type == "list" else f.expr.ilike(f"%{term}%")
                          for f in e.searchable())))
    return q


def columns_for(defn: ReportDefinition) -> List[Field]:
    e = _entity(defn)
    keys = defn.columns or e.default_columns
    seen, cols = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            cols.append(_field(e, k, selectable=True))
    if not cols:
        raise ReportError("Pick at least one column")
    return cols


def compile_rows(defn: ReportDefinition) -> Tuple[Select, List[Field]]:
    e = _entity(defn)
    cols = columns_for(defn)
    selected = [f.expr.label(f.key) for f in cols]
    if e.link:
        selected.append(e.link[1].label("_link_id"))
    q = _where(e, defn, _from(e, select(*selected)))
    sort = _field(e, defn.sort or e.default_sort, selectable=True)
    order = sort.expr.desc() if defn.sort_dir == "desc" else sort.expr.asc()
    return q.order_by(order.nulls_last()), cols


def compile_groups(defn: ReportDefinition) -> Select:
    e = _entity(defn)
    g = _field(e, defn.group_by, selectable=True)
    if g.type == "list":
        raise ReportError(f"{g.label} can't be grouped")
    count = func.count().label("count")
    q = _where(e, defn, _from(e, select(g.expr.label("value"), count)))
    return q.group_by(g.expr).order_by(count.desc())


def compile_count(defn: ReportDefinition) -> Select:
    e = _entity(defn)
    return select(func.count()).select_from(_where(e, defn, _from(e, select(e.base.id))).subquery())


def check_licence(defn: ReportDefinition, modules: Optional[List[str]]) -> None:
    e = _entity(defn)
    if e.module and modules is not None and e.module not in modules:
        raise PermissionError(f"The '{e.module}' module is not enabled in your license")


# ── execution ───────────────────────────────────────────────────────────────
def plain(value: Any) -> Any:
    """JSON/export-friendly value."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    return value


async def run(db: AsyncSession, defn: ReportDefinition, page: int = 1, size: int = 100) -> Dict[str, Any]:
    size = max(1, min(size, MAX_PAGE_SIZE))
    total = (await db.scalar(compile_count(defn))) or 0
    if defn.group_by:
        e = _entity(defn)
        g = _field(e, defn.group_by, selectable=True)
        groups = (await db.execute(compile_groups(defn).limit(500))).all()
        return {
            "kind": "groups", "total": total,
            "group_field": {"key": g.key, "label": g.label, "type": g.type},
            "groups": [{"value": plain(v), "count": c} for v, c in groups],
        }
    q, cols = compile_rows(defn)
    rows = (await db.execute(q.offset((max(page, 1) - 1) * size).limit(size))).mappings().all()
    e = _entity(defn)
    return {
        "kind": "rows", "total": total, "page": page, "size": size,
        "link": e.link[0] if e.link else None,
        "columns": [{"key": f.key, "label": f.label, "type": f.type} for f in cols],
        "rows": [{**{f.key: plain(r[f.key]) for f in cols}, "_link_id": r.get("_link_id")} for r in rows],
    }


async def export_rows(db: AsyncSession, defn: ReportDefinition) -> Tuple[List[Tuple[str, str]], List[List[Any]]]:
    """(header [(key, label)], rows) for file export; grouped reports export value/count."""
    if defn.group_by:
        e = _entity(defn)
        g = _field(e, defn.group_by, selectable=True)
        groups = (await db.execute(compile_groups(defn).limit(MAX_EXPORT_ROWS))).all()
        return [("value", g.label), ("count", "Count")], [[plain(v), c] for v, c in groups]
    q, cols = compile_rows(defn)
    result = await db.execute(q.limit(MAX_EXPORT_ROWS))
    rows = [[plain(r[f.key]) for f in cols] for r in result.mappings()]
    return [(f.key, f.label) for f in cols], rows


def operator_catalog() -> Dict[str, List[Dict[str, str]]]:
    return {t: [{"op": op, "label": OPERATOR_LABELS[op], "value": kind} for op, kind in ops.items()]
            for t, ops in OPERATORS.items()}
