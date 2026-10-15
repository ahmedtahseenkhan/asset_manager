"""
Shared test fixtures.

Uses an in-memory SQLite database so tests run without a running PostgreSQL instance.
SQLite doesn't support all PostgreSQL features (e.g. JSONB operators), but the
correlator and normalizer only use basic ORM operations that work on both.
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from backend.database import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def make_raw(
    source_uid="uid-1",
    hostname="PC-001",
    fqdn="pc-001.corp.local",
    ip_addresses=None,
    mac_addresses=None,
    os_name="Windows 10",
    os_version="10",
    domain="corp.local",
    ou=None,
    last_seen=None,
    extra=None,
):
    from datetime import datetime, timezone
    return {
        "source_uid":    source_uid,
        "hostname":      hostname,
        "fqdn":          fqdn,
        "ip_addresses":  ip_addresses or ["10.0.0.1"],
        "mac_addresses": mac_addresses or ["AA:BB:CC:DD:EE:FF"],
        "os_name":       os_name,
        "os_version":    os_version,
        "domain":        domain,
        "ou":            ou,
        "last_seen":     last_seen or datetime.now(timezone.utc),
        "extra":         extra or {},
    }


# ── API test client ─────────────────────────────────────────────────────────
# A real app instance against a temporary SQLite file built by the migrations,
# with a signed-in admin and a valid license that enables every module.

@pytest.fixture
async def api(tmp_path, monkeypatch):
    import httpx
    from backend.connectors.registry import registry
    from backend.database import get_db
    from backend.licensing.modules import ALL_MODULES
    from backend.licensing.state import license_manager
    from backend.licensing.verifier import LicenseInfo, LicenseStatus
    from backend.main import app
    from backend.migrations import run_migrations
    from backend.models.user import User
    from backend.utils.security import create_access_token, get_password_hash

    db_path = tmp_path / "api.db"
    run_migrations(f"sqlite+aiosqlite:///{db_path}")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    registry.discover_and_register()  # normally done in the app lifespan
    monkeypatch.setattr(license_manager, "_info", LicenseInfo(
        LicenseStatus.VALID, claims={
            "modules": list(ALL_MODULES), "max_assets": 10_000, "max_users": 100,
            "customer": "Test", "expires_at": "2099-01-01",
        },
    ))

    async with session_factory() as s:
        s.add(User(username="admin", email="admin@test.local",
                   hashed_password=get_password_hash("x"), role="admin"))
        await s.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Authorization": f"Bearer {create_access_token('admin')}"},
    ) as client:
        client.session_factory = session_factory  # direct DB access for assertions
        yield client

    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
