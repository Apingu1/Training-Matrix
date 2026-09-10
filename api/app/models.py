from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SecurityRole(Base):
    __tablename__ = "security_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    permissions: Mapped[list["RolePermission"]] = relationship(cascade="all, delete-orphan")


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60), index=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("security_roles.id"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"), primary_key=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(Text)
    security_role_id: Mapped[int] = mapped_column(ForeignKey("security_roles.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    security_role: Mapped[SecurityRole] = relationship()


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class JobRole(Base):
    __tablename__ = "job_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(140))
    department: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserJobRole(Base):
    __tablename__ = "user_job_roles"
    __table_args__ = (UniqueConstraint("user_id", "job_role_id", "effective_from", name="uq_user_job_role_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)
    effective_to: Mapped[date | None] = mapped_column(Date)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    job_role: Mapped[JobRole] = relationship()


class DocumentFamily(Base):
    __tablename__ = "document_families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    document_type: Mapped[str] = mapped_column(String(60), index=True)
    owner_department: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    review_interval_months: Mapped[int] = mapped_column(Integer, default=24)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="family",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.created_at.desc()",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("family_id", "version_label", name="uq_document_family_version"),
        Index("ix_document_version_status_effective", "status", "effective_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("document_families.id"), index=True)
    version_label: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    relative_path: Mapped[str] = mapped_column(String(1000))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_size: Mapped[int] = mapped_column(Integer)
    source_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    change_summary: Mapped[str] = mapped_column(Text)
    training_impact: Mapped[str] = mapped_column(String(40), default="RETRAIN", index=True)
    training_impact_reason: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date | None] = mapped_column(Date)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    released_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    family: Mapped[DocumentFamily] = relationship(back_populates="versions")


class SourceScanRun(Base):
    __tablename__ = "source_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING", index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)


class SourceInventoryFile(Base):
    __tablename__ = "source_inventory_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    extension: Mapped[str] = mapped_column(String(40), index=True)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_size: Mapped[int] = mapped_column(Integer)
    source_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    inferred_code: Mapped[str | None] = mapped_column(String(100), index=True)
    inferred_version: Mapped[str | None] = mapped_column(String(60))
    inferred_title: Mapped[str | None] = mapped_column(String(500))
    inferred_document_type: Mapped[str | None] = mapped_column(String(60))
    inferred_owner_department: Mapped[str | None] = mapped_column(String(120))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_scan_id: Mapped[int] = mapped_column(ForeignKey("source_scan_runs.id"), index=True)
    scan_error: Mapped[str | None] = mapped_column(Text)


class VersionSignature(Base):
    __tablename__ = "version_signatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    meaning: Mapped[str] = mapped_column(String(60))
    statement: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class ControlledCopyIssue(Base):
    __tablename__ = "controlled_copy_issues"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "copy_number",
            name="uq_controlled_copy_version_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id"),
        index=True,
    )
    copy_number: Mapped[str] = mapped_column(String(80))
    department: Mapped[str] = mapped_column(String(120), index=True)
    location: Mapped[str] = mapped_column(String(300))
    issued_to: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="ISSUED", index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    issued_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closure_reason: Mapped[str | None] = mapped_column(Text)

    document_version: Mapped[DocumentVersion] = relationship()


class RoleDocumentRequirement(Base):
    __tablename__ = "role_document_requirements"
    __table_args__ = (UniqueConstraint("job_role_id", "document_family_id", name="uq_role_document_requirement"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_role_id: Mapped[int] = mapped_column(ForeignKey("job_roles.id"), index=True)
    document_family_id: Mapped[int] = mapped_column(ForeignKey("document_families.id"), index=True)
    requirement_type: Mapped[str] = mapped_column(String(60), default="READ_UNDERSTAND")
    due_days: Mapped[int] = mapped_column(Integer, default=14)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job_role: Mapped[JobRole] = relationship()
    document_family: Mapped[DocumentFamily] = relationship()


class TrainingAssignment(Base):
    __tablename__ = "training_assignments"
    __table_args__ = (UniqueConstraint("user_id", "document_version_id", name="uq_user_document_assignment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="ASSIGNED", index=True)
    requirement_type: Mapped[str] = mapped_column(String(60), default="READ_UNDERSTAND")
    is_individual: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    document_version: Mapped[DocumentVersion] = relationship()
    sources: Mapped[list["AssignmentSource"]] = relationship(cascade="all, delete-orphan")


class AssignmentSource(Base):
    __tablename__ = "assignment_sources"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("training_assignments.id"), primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("role_document_requirements.id"), primary_key=True)


class TrainingAcknowledgement(Base):
    __tablename__ = "training_acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("training_assignments.id"), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    document_version_id: Mapped[int] = mapped_column(ForeignKey("document_versions.id"), index=True)
    statement: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(40), default="PASSWORD_REAUTH")
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    session_id: Mapped[str] = mapped_column(String(36))


class AssignmentNotificationState(Base):
    __tablename__ = "assignment_notification_states"

    assignment_id: Mapped[int] = mapped_column(ForeignKey("training_assignments.id"), primary_key=True)
    assignment_assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assignment_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ComplianceNotificationState(Base):
    __tablename__ = "compliance_notification_states"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    was_below_threshold: Mapped[bool] = mapped_column(Boolean, default=False)
    last_compliance_percent: Mapped[str] = mapped_column(String(20), default="100.0")
    last_threshold_percent: Mapped[str] = mapped_column(String(20), default="80.0")
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EmailNotificationDelivery(Base):
    __tablename__ = "email_notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_type: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(254), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created_event", "created_at", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(500), unique=True)
    backup_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), index=True)
    database_name: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
