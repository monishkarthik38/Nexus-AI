"""Add a tenant-scoped durable ingestion queue."""

from alembic import op

from app.database.ingestion_models import IngestionJob

revision = "003_durable_ingestion"
down_revision = "002_tenant_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    IngestionJob.__table__.create(op.get_bind(), checkfirst=True)
    op.execute("ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ingestion_jobs")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ingestion_jobs
        USING (
            current_user = 'nexus_worker'
            OR owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
        WITH CHECK (
            current_user = 'nexus_worker'
            OR owner_id = NULLIF(current_setting('app.current_user_id', true), '')
        )
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Durable ingestion queue migrations are intentionally irreversible."
    )
