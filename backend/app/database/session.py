import os
from collections.abc import AsyncGenerator
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import Session, SessionTransaction
from fastapi import Depends
from app.auth import CurrentUser, get_current_user
from app.config import settings, validate_runtime_config
from app.database.models import Base

# Register non-core models with metadata for local development schema creation.
from app.database import ingestion_models as _ingestion_models

class TenantAwareSession(Session):
    pass


@event.listens_for(TenantAwareSession, "after_begin")
def _set_transaction_tenant(
    session: Session,
    _transaction: SessionTransaction,
    connection: Connection,
) -> None:
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None or connection.dialect.name != "postgresql":
        return

    connection.execute(
        text("SELECT set_config('app.current_user_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


# Ensure storage directory exists
os.makedirs(settings.STORAGE_DIR, exist_ok=True)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
    sync_session_class=TenantAwareSession,
)


TENANT_RLS_TABLES = (
    "documents",
    "document_chunks",
    "conversations",
    "messages",
    "research_reports",
    "evaluation_runs",
    "evidence_annotations",
    "ingestion_jobs",
)


async def verify_postgres_rls() -> None:
    async with engine.connect() as connection:
        version_result = await connection.execute(text(
            "SELECT version_num FROM alembic_version"
        ))
        applied_revision = version_result.scalar_one_or_none()
        if applied_revision != "003_durable_ingestion":
            raise RuntimeError(
                "PostgreSQL schema is not at revision 003_durable_ingestion; "
                "run `alembic upgrade head` with the migration role"
            )

        role_result = await connection.execute(text(
            """
            SELECT current_role.rolsuper, current_role.rolbypassrls,
                   EXISTS (
                       SELECT 1
                       FROM pg_roles AS privileged_role
                       WHERE (privileged_role.rolsuper OR privileged_role.rolbypassrls)
                         AND pg_has_role(current_role.rolname, privileged_role.oid, 'MEMBER')
                   ) AS has_privileged_membership
            FROM pg_roles AS current_role
            WHERE current_role.rolname = current_user
            """
        ))
        role = role_result.one_or_none()
        if (
            role is None
            or role.rolsuper
            or role.rolbypassrls
            or role.has_privileged_membership
        ):
            raise RuntimeError(
                "PostgreSQL application role must be a non-superuser without BYPASSRLS"
            )

        schema_result = await connection.execute(text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   p.permissive, p.qual, p.with_check
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            LEFT JOIN pg_policies AS p
              ON p.schemaname = n.nspname
             AND p.tablename = c.relname
             AND p.policyname = 'tenant_isolation'
            WHERE n.nspname = current_schema()
              AND c.relname = ANY(CAST(:table_names AS text[]))
            """
        ), {"table_names": list(TENANT_RLS_TABLES)})
        configured = {
            row.relname: row
            for row in schema_result
        }

    missing = set(TENANT_RLS_TABLES) - configured.keys()
    if missing:
        raise RuntimeError(
            "PostgreSQL tenant RLS is not configured for tables: "
            + ", ".join(sorted(missing))
        )

    invalid = [
        table_name
        for table_name, row in configured.items()
        if not row.relrowsecurity
        or not row.relforcerowsecurity
        or row.permissive != "PERMISSIVE"
        or not row.qual
        or not row.with_check
        or "app.current_user_id" not in row.qual
        or "app.current_user_id" not in row.with_check
    ]
    if invalid:
        raise RuntimeError(
            "PostgreSQL tenant RLS is missing, not forced, or has an invalid policy for: "
            + ", ".join(sorted(invalid))
        )


async def init_db() -> None:
    validate_runtime_config()
    if settings.ENVIRONMENT.strip().lower() == "production":
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Production startup requires PostgreSQL")
        await verify_postgres_rls()
        from app.storage import StorageError, get_document_storage

        try:
            await get_document_storage().verify_private_bucket()
        except StorageError as exc:
            raise RuntimeError(
                "Production startup requires an accessible private Supabase Storage bucket"
            ) from exc
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        def migrate_additive_schema(sync_conn):
            inspector = inspect(sync_conn)
            additions = {
                "documents": {
                    "media_type": "VARCHAR(24) NOT NULL DEFAULT 'pdf'",
                    "mime_type": "VARCHAR(128)",
                    "duration_seconds": "INTEGER",
                    "checksum_sha256": "VARCHAR(128)",
                },
                "evaluation_runs": {
                    "owner_id": "VARCHAR(64) NOT NULL DEFAULT 'default_user'",
                },
                "research_reports": {
                    "report_type": "VARCHAR(32) NOT NULL DEFAULT 'executive_dossier'",
                },
                "document_chunks": {
                    "locator_type": "VARCHAR(24) NOT NULL DEFAULT 'page'",
                    "locator_value": "VARCHAR(128)",
                },
            }
            for table_name, columns in additions.items():
                existing = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name, sql_type in columns.items():
                    if column_name not in existing:
                        sync_conn.exec_driver_sql(
                            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"
                        )
        await conn.run_sync(migrate_additive_schema)

def set_session_tenant(session: AsyncSession, tenant_id: str) -> None:
    if not tenant_id:
        raise ValueError("A verified tenant identity is required for database access")
    session.sync_session.info["tenant_id"] = tenant_id


async def get_db(
    user: CurrentUser = Depends(get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        set_session_tenant(session, user.id)
        yield session
