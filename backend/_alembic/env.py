import asyncio
import sys
import os
from logging.config import fileConfig

# Add project root to python path so we can `import backend...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import pool

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from backend.config import settings
from backend.database import Base
import backend.models  # noqa: F401 — registers every model on Base.metadata

config = context.config

# Only configure logging when invoked from the alembic CLI; when the app runs
# migrations programmatically it has already set up JSON logging.
if config.config_file_name is not None and not config.attributes.get("connection"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables that live in the database but are not ours to migrate.
_EXTERNAL_TABLES = {"apscheduler_jobs"}  # created by APScheduler's SQLAlchemyJobStore


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _EXTERNAL_TABLES:
        return False
    return True


config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it (`alembic upgrade --sql`)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    # backend.migrations passes its own (locked) connection; the CLI does not.
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
