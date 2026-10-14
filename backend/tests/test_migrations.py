"""
Migrations must build exactly the schema the models describe. If this fails
after a model change, generate a revision:

    cd backend && ./.venv/bin/alembic revision --autogenerate -m "<what changed>"
"""
from sqlalchemy import create_engine, inspect

from backend.database import Base
from backend.migrations import run_migrations, schema_drift


def _urls(tmp_path):
    path = tmp_path / "migrations.db"
    return f"sqlite+aiosqlite:///{path}", f"sqlite:///{path}"


def test_fresh_database_matches_models(tmp_path):
    app_url, sync_url = _urls(tmp_path)
    run_migrations(app_url)

    with create_engine(sync_url).connect() as conn:
        assert schema_drift(conn) == []


def test_running_twice_is_a_noop(tmp_path):
    app_url, sync_url = _urls(tmp_path)
    run_migrations(app_url)
    run_migrations(app_url)

    with create_engine(sync_url).connect() as conn:
        assert schema_drift(conn) == []


def test_legacy_create_all_database_is_adopted(tmp_path):
    """Pre-Alembic installs: tables exist (some missing), no alembic_version."""
    app_url, sync_url = _urls(tmp_path)
    engine = create_engine(sync_url)
    legacy = [t for name, t in Base.metadata.tables.items() if name != "vulnerabilities"]
    Base.metadata.create_all(engine, tables=legacy)

    run_migrations(app_url)

    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "vulnerabilities" in tables
        assert "alembic_version" in tables
        assert schema_drift(conn) == []
