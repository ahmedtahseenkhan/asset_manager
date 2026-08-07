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
