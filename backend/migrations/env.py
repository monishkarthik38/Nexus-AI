from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
if not database_url.startswith("postgresql+asyncpg://"):
    raise RuntimeError(
        "Alembic migrations require DATABASE_URL=postgresql+asyncpg://..."
    )
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    raise RuntimeError(
        "Offline SQL generation is disabled: the baseline migration inspects and "
        "upgrades existing schemas. Run `alembic upgrade head` against PostgreSQL."
    )


def _run_sync_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if "+asyncpg" in database_url:
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        async def run_async_migrations() -> None:
            async with connectable.connect() as connection:
                await connection.run_sync(_run_sync_migrations)
            await connectable.dispose()

        import asyncio

        asyncio.run(run_async_migrations())
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            _run_sync_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
