"""Enable and force tenant row-level security."""

from pathlib import Path

from alembic import op

revision = "002_tenant_rls"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migration_sql = Path(__file__).parents[1] / "001_enable_tenant_rls.sql"
    statements = migration_sql.read_text(encoding="utf-8").split(";")
    for statement in statements:
        cleaned = "\n".join(
            line for line in statement.splitlines()
            if not line.lstrip().startswith("--")
        ).strip()
        if cleaned and cleaned.upper() not in {"BEGIN", "COMMIT"}:
            op.execute(cleaned)


def downgrade() -> None:
    raise NotImplementedError(
        "Tenant RLS cannot be disabled by an application migration downgrade."
    )
