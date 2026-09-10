"""Persistent email notification delivery and state.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("assignment_notification_states"):
        op.create_table(
            "assignment_notification_states",
            sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("training_assignments.id"), primary_key=True),
            sa.Column("assignment_assigned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("assignment_notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_overdue_notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_assignment_notification_states_assignment_notified_at",
            "assignment_notification_states",
            ["assignment_notified_at"],
        )
        op.create_index(
            "ix_assignment_notification_states_last_overdue_notified_at",
            "assignment_notification_states",
            ["last_overdue_notified_at"],
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("compliance_notification_states"):
        op.create_table(
            "compliance_notification_states",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("was_below_threshold", sa.Boolean(), nullable=False),
            sa.Column("last_compliance_percent", sa.String(length=20), nullable=False),
            sa.Column("last_threshold_percent", sa.String(length=20), nullable=False),
            sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_compliance_notification_states_last_notified_at",
            "compliance_notification_states",
            ["last_notified_at"],
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table("email_notification_deliveries"):
        op.create_table(
            "email_notification_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("notification_type", sa.String(length=40), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("recipient_email", sa.String(length=254), nullable=False),
            sa.Column("subject", sa.String(length=500), nullable=False),
            sa.Column("body_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("dedupe_key", sa.String(length=200), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("dedupe_key", name="uq_email_notification_delivery_dedupe_key"),
        )
        for name, columns in (
            ("ix_email_notification_deliveries_notification_type", ["notification_type"]),
            ("ix_email_notification_deliveries_user_id", ["user_id"]),
            ("ix_email_notification_deliveries_recipient_email", ["recipient_email"]),
            ("ix_email_notification_deliveries_status", ["status"]),
            ("ix_email_notification_deliveries_scheduled_for", ["scheduled_for"]),
            ("ix_email_notification_deliveries_sent_at", ["sent_at"]),
            ("ix_email_notification_deliveries_dedupe_key", ["dedupe_key"]),
            ("ix_email_notification_deliveries_created_at", ["created_at"]),
        ):
            op.create_index(name, "email_notification_deliveries", columns)


def downgrade() -> None:
    op.drop_table("email_notification_deliveries")
    op.drop_table("compliance_notification_states")
    op.drop_table("assignment_notification_states")
