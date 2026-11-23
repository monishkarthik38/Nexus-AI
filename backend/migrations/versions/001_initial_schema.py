"""Create application schema and apply safe additive compatibility columns."""

from alembic import op
from sqlalchemy import inspect

from app.database.models import Base

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    Base.metadata.create_all(connection, checkfirst=True)

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
    inspector = inspect(connection)
    for table_name, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, sql_type in columns.items():
            if column_name not in existing:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"
                )


def downgrade() -> None:
    raise NotImplementedError(
        "The initial schema migration is a baseline and is intentionally irreversible."
    )
