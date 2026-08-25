"""Persistent controlled-source discovery inventory.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("source_scan_runs"):
        op.create_table(
            "source_scan_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trigger", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("counts_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        )
        op.create_index("ix_source_scan_runs_trigger", "source_scan_runs", ["trigger"])
        op.create_index("ix_source_scan_runs_status", "source_scan_runs", ["status"])
        op.create_index("ix_source_scan_runs_requested_by", "source_scan_runs", ["requested_by"])
        op.create_index("ix_source_scan_runs_started_at", "source_scan_runs", ["started_at"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("source_inventory_files"):
        op.create_table(
            "source_inventory_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("relative_path", sa.String(length=1000), nullable=False),
            sa.Column("extension", sa.String(length=40), nullable=False),
            sa.Column("is_supported", sa.Boolean(), nullable=False),
            sa.Column("source_size", sa.Integer(), nullable=False),
            sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_sha256", sa.String(length=64), nullable=True),
            sa.Column("inferred_code", sa.String(length=100), nullable=True),
            sa.Column("inferred_version", sa.String(length=60), nullable=True),
            sa.Column("inferred_title", sa.String(length=500), nullable=True),
            sa.Column("inferred_document_type", sa.String(length=60), nullable=True),
            sa.Column("inferred_owner_department", sa.String(length=120), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_scan_id", sa.Integer(), sa.ForeignKey("source_scan_runs.id"), nullable=False),
            sa.Column("scan_error", sa.Text(), nullable=True),
            sa.UniqueConstraint("relative_path", name="uq_source_inventory_relative_path"),
        )
        for name, columns in (
            ("ix_source_inventory_files_relative_path", ["relative_path"]),
            ("ix_source_inventory_files_extension", ["extension"]),
            ("ix_source_inventory_files_is_supported", ["is_supported"]),
            ("ix_source_inventory_files_source_sha256", ["source_sha256"]),
            ("ix_source_inventory_files_inferred_code", ["inferred_code"]),
            ("ix_source_inventory_files_last_seen_at", ["last_seen_at"]),
            ("ix_source_inventory_files_missing_since", ["missing_since"]),
            ("ix_source_inventory_files_last_scan_id", ["last_scan_id"]),
        ):
            op.create_index(name, "source_inventory_files", columns)


def downgrade() -> None:
    op.drop_table("source_inventory_files")
    op.drop_table("source_scan_runs")
