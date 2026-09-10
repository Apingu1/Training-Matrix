from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AssignmentNotificationState,
    DocumentFamily,
    DocumentVersion,
    EmailNotificationDelivery,
    JobRole,
    SecurityRole,
    SystemSetting,
    TrainingAssignment,
    User,
    UserJobRole,
)
from app.security import hash_password, utcnow
from app.seed import seed_database
from app.services import notifications


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def add_released_sop(db: Session, *, code: str, title: str, created_by: int) -> DocumentVersion:
    family = DocumentFamily(
        code=code,
        title=title,
        document_type="SOP",
        owner_department="Production",
        review_interval_months=24,
        is_active=True,
        created_by=created_by,
    )
    db.add(family)
    db.flush()
    version = DocumentVersion(
        family_id=family.id,
        version_label="V01",
        status="RELEASED",
        relative_path=f"SOP/{code}.V01.pdf",
        source_sha256="a" * 64,
        source_size=100,
        source_modified_at=utcnow(),
        change_summary="Initial issue",
        training_impact="RETRAIN",
        effective_at=utcnow(),
        created_by=created_by,
    )
    db.add(version)
    db.flush()
    return version


def test_notification_digests_retry_and_recurring_overdue(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        seed_database(db)
        admin = db.scalar(select(User).where(User.username == "admin"))
        operator_role = db.scalar(select(SecurityRole).where(SecurityRole.code == "OPERATOR"))
        assert admin and operator_role
        job_role = JobRole(
            code="EMAIL_TEST_OPERATOR",
            name="Email Test Operator",
            department="Production",
            is_active=True,
        )
        operator = User(
            username="email.operator",
            display_name="Email Operator",
            email="operator@example.com",
            password_hash=hash_password("Password8"),
            security_role_id=operator_role.id,
            is_active=True,
            must_change_password=False,
        )
        db.add_all([job_role, operator])
        db.flush()
        db.add(
            UserJobRole(
                user_id=operator.id,
                job_role_id=job_role.id,
                effective_from=date.today(),
                assigned_by=admin.id,
                reason="Notification integration test",
            )
        )

        versions = [
            add_released_sop(db, code="ES.SOP.901", title="Email Test One", created_by=admin.id),
            add_released_sop(db, code="ES.SOP.902", title="Email Test Two", created_by=admin.id),
        ]
        enabled_since = utcnow()
        for version in versions:
            db.add(
                TrainingAssignment(
                    user_id=operator.id,
                    document_version_id=version.id,
                    status="ASSIGNED",
                    requirement_type="READ_UNDERSTAND",
                    assigned_at=enabled_since + timedelta(seconds=1),
                    due_at=enabled_since + timedelta(days=7),
                    assigned_by=admin.id,
                )
            )

        encrypted_password = notifications.encrypt_smtp_password("smtp-secret-value")
        assert "smtp-secret-value" not in encrypted_password
        assert notifications.decrypt_smtp_password(encrypted_password) == "smtp-secret-value"
        configuration = {
            "notification_email_enabled": "true",
            "notification_smtp_host": "smtp.example.com",
            "notification_smtp_port": "587",
            "notification_smtp_security": "STARTTLS",
            "notification_smtp_username": "training@example.com",
            "notification_smtp_password": encrypted_password,
            "notification_sender_name": "Eaststone Training Matrix",
            "notification_sender_email": "training@example.com",
            "notification_overdue_frequency_days": "1",
            "notification_enabled_since": enabled_since.isoformat(),
        }
        for key, value in configuration.items():
            set_setting(db, key, value)
        db.commit()

        public = notifications.public_notification_settings(db)
        assert public["smtp_password_configured"] is True
        assert "smtp_password" not in public

        def fail_delivery(*_args, **_kwargs):
            raise OSError("simulated SMTP outage")

        monkeypatch.setattr(notifications, "_send_email", fail_delivery)
        failed_cycle = notifications.run_notification_cycle(db)
        assert failed_cycle == {
            "enabled": True,
            "queued": 2,
            "queued_by_type": {
                "new_assignment": 1,
                "overdue": 0,
                "below_threshold": 1,
            },
            "sent": 0,
            "failed": 2,
        }
        failed = db.scalars(select(EmailNotificationDelivery).where(EmailNotificationDelivery.status == "FAILED")).all()
        assert len(failed) == 2

        messages = []

        def capture_delivery(_configuration, *, recipient, subject, body_text):
            messages.append({"recipient": recipient, "subject": subject, "body": body_text})

        monkeypatch.setattr(notifications, "_send_email", capture_delivery)
        retry_cycle = notifications.run_notification_cycle(db, force=True)
        assert retry_cycle["queued"] == 0
        assert retry_cycle["sent"] == 2
        assert retry_cycle["failed"] == 0
        assignment_message = next(item for item in messages if item["subject"] == "Training assigned")
        assert assignment_message["recipient"] == "operator@example.com"
        assert "ES.SOP.901" in assignment_message["body"]
        assert "ES.SOP.902" in assignment_message["body"]
        assert "Target date:" in assignment_message["body"]

        assignments = db.scalars(select(TrainingAssignment).where(TrainingAssignment.user_id == operator.id)).all()
        for assignment in assignments:
            assignment.due_at = utcnow() - timedelta(days=1)
        db.commit()
        messages.clear()
        overdue_cycle = notifications.run_notification_cycle(db, force=True)
        assert overdue_cycle["queued_by_type"]["overdue"] == 1
        assert overdue_cycle["sent"] == 1
        assert len(messages) == 1
        assert messages[0]["subject"] == "Training overdue"
        assert "required training is overdue" in messages[0]["body"]

        immediate_repeat = notifications.run_notification_cycle(db, force=True)
        assert immediate_repeat["queued"] == 0
        assert immediate_repeat["sent"] == 0

        for assignment in assignments:
            state = db.get(AssignmentNotificationState, assignment.id)
            assert state and state.last_overdue_notified_at
            state.last_overdue_notified_at = utcnow() - timedelta(days=2)
        db.commit()
        recurring = notifications.run_notification_cycle(db, force=True)
        assert recurring["queued_by_type"]["overdue"] == 1
        assert recurring["sent"] == 1
