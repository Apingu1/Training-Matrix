"""Initial controlled documents and training schema.

Revision ID: 0001
Revises: None
"""

from alembic import op
from app import models  # noqa: F401
from app.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_released_version_per_family "
        "ON document_versions (family_id) WHERE status = 'RELEASED'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_compliance_record_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Compliance records are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("audit_events", "training_acknowledgements", "version_signatures"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_compliance_record_mutation();
            """
        )


def downgrade() -> None:
    for table in ("audit_events", "training_acknowledgements", "version_signatures"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_compliance_record_mutation()")
    Base.metadata.drop_all(bind=op.get_bind())
