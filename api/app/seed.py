from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, runtime
from .models import Permission, RolePermission, SecurityRole, SystemSetting, User
from .security import hash_password

PERMISSIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "documents.view",
        "View controlled documents",
        "Open released controlled documents",
        "Documents",
    ),
    (
        "documents.manage",
        "Manage documents",
        "Create documents and revisions",
        "Documents",
    ),
    (
        "documents.review",
        "Review documents",
        "Submit and return document revisions",
        "Documents",
    ),
    (
        "documents.approve",
        "Approve and release",
        "Approve, release and retire revisions",
        "Documents",
    ),
    (
        "documents.source_download",
        "Download source files",
        "Download authorised original PDF or DOCX files",
        "Documents",
    ),
    (
        "training.view_own",
        "View own training",
        "View personal assignments and history",
        "Training",
    ),
    (
        "training.acknowledge",
        "Acknowledge training",
        "Sign read-and-understood assignments",
        "Training",
    ),
    (
        "training.view_team",
        "View team training",
        "View role and user compliance",
        "Training",
    ),
    (
        "training.manage",
        "Manage training",
        "Maintain role requirements and individual assignments",
        "Training",
    ),
    (
        "training.waive",
        "Authorise training exceptions",
        "Waive or close assignments with a reason",
        "Training",
    ),
    (
        "job_roles.manage",
        "Manage job roles",
        "Create roles and assign people",
        "Administration",
    ),
    (
        "users.manage",
        "Manage users",
        "Create, amend and reset user accounts",
        "Administration",
    ),
    (
        "security_roles.manage",
        "Manage security roles",
        "Maintain permission bundles",
        "Administration",
    ),
    ("audit.view", "View audit trail", "Search and export GMP audit records", "Audit"),
    (
        "backups.manage",
        "Manage backups",
        "Create, verify and restore database backups",
        "System",
    ),
    (
        "settings.manage",
        "Manage settings",
        "Maintain system settings and source status",
        "System",
    ),
)


ROLE_DEFINITIONS: dict[str, tuple[str, str, set[str] | str]] = {
    "ADMIN": ("System Administrator", "Full technical administration", "ALL"),
    "QA_APPROVER": (
        "QA Approver",
        "Independent document approval and QA oversight",
        {
            "documents.view",
            "documents.manage",
            "documents.review",
            "documents.approve",
            "documents.source_download",
            "training.view_own",
            "training.acknowledge",
            "training.view_team",
            "training.manage",
            "training.waive",
            "job_roles.manage",
            "audit.view",
        },
    ),
    "DOCUMENT_CONTROLLER": (
        "Document Controller",
        "Document metadata, revisions and curricula",
        {
            "documents.view",
            "documents.manage",
            "documents.review",
            "documents.source_download",
            "training.view_own",
            "training.acknowledge",
            "training.view_team",
            "training.manage",
            "job_roles.manage",
            "audit.view",
        },
    ),
    "MANAGER_TRAINER": (
        "Manager / Trainer",
        "Team compliance and training management",
        {
            "documents.view",
            "training.view_own",
            "training.acknowledge",
            "training.view_team",
            "training.manage",
            "training.waive",
        },
    ),
    "OPERATOR": (
        "Operator",
        "Read-only documents and personal training",
        {"documents.view", "training.view_own", "training.acknowledge"},
    ),
    "AUDITOR": (
        "Auditor",
        "Read-only compliance inspection access",
        {"documents.view", "training.view_team", "audit.view"},
    ),
}


DEFAULT_SETTINGS = {
    "maintenance_mode": (
        "false",
        "Blocks ordinary write operations during controlled maintenance",
    ),
    "backup_time": (settings.backup_time, "Local daily automatic backup time"),
    "backup_timezone": (
        settings.backup_timezone,
        "IANA timezone used by the backup scheduler",
    ),
    "backup_retention_days": (
        str(settings.backup_retention_days),
        "Days to retain automatic backups",
    ),
    "training_default_due_days": (
        "14",
        "Default completion period for training assignments",
    ),
    "active_compliance_threshold_percent": (
        "80",
        "Minimum active SOP training compliance percentage before an operator is alerted",
    ),
    "session_idle_minutes": (
        str(settings.session_idle_minutes),
        "Minutes without human activity before the current session is logged out",
    ),
    "session_absolute_minutes": (
        str(settings.jwt_expires_minutes),
        "Maximum session duration in minutes regardless of activity",
    ),
    "acknowledgement_statement": (
        "I confirm that I have read and understood this document and will comply with its requirements.",
        "Controlled read-and-understood attestation",
    ),
    "source_scan_interval_minutes": (
        "60",
        "Automatic recursive controlled-source discovery interval in minutes",
    ),
}


def seed_database(db: Session) -> None:
    for code, name, description, category in PERMISSIONS:
        permission = db.get(Permission, code)
        if permission is None:
            db.add(Permission(code=code, name=name, description=description, category=category))
        else:
            permission.name = name
            permission.description = description
            permission.category = category
    db.flush()

    all_codes = {item[0] for item in PERMISSIONS}
    roles: dict[str, SecurityRole] = {}
    for code, (name, description, configured_permissions) in ROLE_DEFINITIONS.items():
        role = db.scalar(select(SecurityRole).where(SecurityRole.code == code))
        created = role is None
        if role is None:
            role = SecurityRole(
                code=code,
                name=name,
                description=description,
                is_system=True,
                is_active=True,
            )
            db.add(role)
            db.flush()
        else:
            role.is_system = True
        roles[code] = role
        if created or code == "ADMIN":
            desired = all_codes if configured_permissions == "ALL" else configured_permissions
            existing = set(
                db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)).all()
            )
            for permission_code in desired - existing:
                db.add(RolePermission(role_id=role.id, permission_code=permission_code))
            for permission_code in existing - desired:
                mapping = db.get(RolePermission, (role.id, permission_code))
                if mapping:
                    db.delete(mapping)

    admin = db.scalar(select(User).where(User.username == settings.initial_admin_username.lower()))
    if admin is None:
        admin = User(
            username=settings.initial_admin_username.lower(),
            display_name="System Administrator",
            email=None,
            password_hash=hash_password(settings.initial_admin_password),
            security_role_id=roles["ADMIN"].id,
            is_active=True,
            must_change_password=True,
        )
        db.add(admin)

    for key, (value, description) in DEFAULT_SETTINGS.items():
        if db.get(SystemSetting, key) is None:
            db.add(SystemSetting(key=key, value=value, description=description))
    db.commit()


def main() -> None:
    Base.metadata.create_all(runtime.engine)
    with runtime.session() as db:
        seed_database(db)


if __name__ == "__main__":
    main()
