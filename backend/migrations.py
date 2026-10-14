"""
Schema migrations. Runs at API startup (see main.py) and from the CLI:

    python -m backend.migrations

Alembic is the single source of truth for the schema. Three database states
are handled:

- empty                      -> `upgrade head` builds everything
- managed (has alembic_version) -> `upgrade head` applies pending revisions
- legacy (tables, no alembic_version) — installs from before Alembic was wired
  in, whose schema came from `Base.metadata.create_all`. They are adopted:
  missing baseline tables are created, the DB is stamped at the baseline, and
  later revisions apply normally.

A Postgres advisory lock serialises concurrent starters (several API workers
or replicas booting at once), so only one of them migrates.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.pool import NullPool

from backend.config import settings
from backend.database import Base
import backend.models  # noqa: F401 — registers every model on Base.metadata

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent
_ADVISORY_LOCK_ID = 74_141_200_001  # arbitrary, unique to this application

BASELINE_REVISION = "0001_baseline"
# Tables created by the baseline revision. Legacy installs are only topped up
# with these — tables added by later revisions are left to those revisions.
_BASELINE_TABLES = frozenset({
    "agent_tokens", "alert_rules", "app_license_activations", "asset_lifecycle_events",
    "asset_relationships", "assets", "audit_logs", "connector_configs", "contract_assets",
    "contracts", "device_sources", "devices", "entitlement_assignments", "entitlements",
    "installed_software", "notification_log", "smtp_settings", "sync_logs", "users",
    "vulnerabilities",
})
_EXTERNAL_TABLES = {"apscheduler_jobs"}  # owned by APScheduler, not by us

# The app's async drivers, mapped to the sync drivers Alembic runs on.
_SYNC_DRIVERS = {"postgresql+asyncpg": "postgresql+psycopg2", "sqlite+aiosqlite": "sqlite"}


def _sync_url(url: str) -> str:
    u = make_url(url)
    return u.set(drivername=_SYNC_DRIVERS.get(u.drivername, u.drivername)).render_as_string(
        hide_password=False
    )


def _alembic_config(connection: Connection) -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "_alembic"))
    cfg.attributes["connection"] = connection
    return cfg


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and name in _EXTERNAL_TABLES)


def _adopt_legacy_schema(conn: Connection, cfg: Config, existing: set[str]) -> None:
    missing = sorted(_BASELINE_TABLES - existing)
    logger.warning(
        "Database has tables but no migration history — adopting it at %s "
        "(creating %d missing table(s): %s)",
        BASELINE_REVISION, len(missing), ", ".join(missing) or "none",
    )
    if missing:
        Base.metadata.create_all(conn, tables=[Base.metadata.tables[t] for t in missing])
    command.stamp(cfg, BASELINE_REVISION)


def schema_drift(conn: Connection) -> list:
    """Differences between the live database and the models (empty = in sync)."""
    ctx = MigrationContext.configure(
        conn, opts={"include_object": _include_object, "compare_type": True}
    )
    # Reflection logs one INFO line per SERIAL column; keep startup logs clean.
    ddl_logger = logging.getLogger("alembic.ddl.postgresql")
    previous = ddl_logger.level
    ddl_logger.setLevel(logging.WARNING)
    try:
        return compare_metadata(ctx, Base.metadata)
    finally:
        ddl_logger.setLevel(previous)


def run_migrations(database_url: str | None = None) -> None:
    engine = create_engine(_sync_url(database_url or settings.database_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            is_pg = conn.dialect.name == "postgresql"
            if is_pg:
                conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _ADVISORY_LOCK_ID})
                conn.commit()
            try:
                # One transaction: Postgres DDL is transactional, so a failed
                # upgrade leaves the schema exactly as it was.
                with conn.begin():
                    cfg = _alembic_config(conn)
                    existing = set(inspect(conn).get_table_names())
                    if "alembic_version" not in existing and existing & _BASELINE_TABLES:
                        _adopt_legacy_schema(conn, cfg, existing)
                    command.upgrade(cfg, "head")

                    drift = schema_drift(conn)
                    if drift:
                        logger.warning(
                            "Database schema differs from the models in %d place(s) — "
                            "a migration is missing or the DB was changed by hand: %s",
                            len(drift), drift,
                        )
            finally:
                if is_pg:
                    conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _ADVISORY_LOCK_ID})
                    conn.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run_migrations()
    logger.info("Database is at the latest schema revision.")
