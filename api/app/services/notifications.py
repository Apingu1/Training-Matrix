from __future__ import annotations

import base64
import hashlib
import re
import smtplib
import ssl
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..models import (
    AssignmentNotificationState,
    ComplianceNotificationState,
    DocumentFamily,
    DocumentVersion,
    EmailNotificationDelivery,
    JobRole,
    SystemSetting,
    TrainingAssignment,
    User,
    UserJobRole,
)
from .training import active_role_condition, displayed_status

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SMTP_SECURITY_OPTIONS = {"STARTTLS", "SSL", "NONE"}
MAX_DELIVERY_ATTEMPTS = 12
DELIVERY_BATCH_SIZE = 50

SETTING_DEFAULTS = {
    "notification_email_enabled": "false",
    "notification_smtp_host": "",
    "notification_smtp_port": "587",
    "notification_smtp_security": "STARTTLS",
    "notification_smtp_username": "",
    "notification_smtp_password": "",
    "notification_sender_name": "Eaststone Training Matrix",
    "notification_sender_email": "",
    "notification_overdue_frequency_days": "1",
    "notification_enabled_since": "",
}


class NotificationConfigurationError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def setting_value(db: Session, key: str) -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else SETTING_DEFAULTS[key]


def email_enabled(db: Session) -> bool:
    return setting_value(db, "notification_email_enabled").strip().lower() == "true"


def valid_email(value: str | None) -> bool:
    return bool(value and len(value) <= 254 and EMAIL_PATTERN.fullmatch(value.strip()))


def encrypt_smtp_password(value: str) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(f"eaststone-smtp-v1|{settings.jwt_secret}".encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return "fernet:v1:" + Fernet(key).encrypt(value.encode()).decode()


def decrypt_smtp_password(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("fernet:v1:"):
        raise NotificationConfigurationError("The stored SMTP password format is invalid; enter the password again")
    digest = hashlib.sha256(f"eaststone-smtp-v1|{settings.jwt_secret}".encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    try:
        return Fernet(key).decrypt(value.removeprefix("fernet:v1:").encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise NotificationConfigurationError(
            "The SMTP password cannot be decrypted on this installation; enter the password again"
        ) from exc


def public_notification_settings(db: Session) -> dict:
    enabled_since = setting_value(db, "notification_enabled_since")
    user_rows = db.execute(select(User.is_active, User.email)).all()
    active_users = [row for row in user_rows if row.is_active]
    users_with_email = sum(1 for row in active_users if valid_email(row.email))
    return {
        "enabled": email_enabled(db),
        "smtp_host": setting_value(db, "notification_smtp_host"),
        "smtp_port": int(setting_value(db, "notification_smtp_port")),
        "smtp_security": setting_value(db, "notification_smtp_security"),
        "smtp_username": setting_value(db, "notification_smtp_username"),
        "smtp_password_configured": bool(setting_value(db, "notification_smtp_password")),
        "sender_name": setting_value(db, "notification_sender_name"),
        "sender_email": setting_value(db, "notification_sender_email"),
        "overdue_frequency_days": int(setting_value(db, "notification_overdue_frequency_days")),
        "enabled_since": enabled_since or None,
        "active_user_count": len(active_users),
        "users_with_email_count": users_with_email,
        "users_without_email_count": len(active_users) - users_with_email,
    }


def smtp_configuration(db: Session) -> dict:
    host = setting_value(db, "notification_smtp_host").strip()
    sender_email = setting_value(db, "notification_sender_email").strip()
    username = setting_value(db, "notification_smtp_username").strip()
    security = setting_value(db, "notification_smtp_security").strip().upper()
    try:
        port = int(setting_value(db, "notification_smtp_port"))
    except ValueError as exc:
        raise NotificationConfigurationError("SMTP port is invalid") from exc
    if not host:
        raise NotificationConfigurationError("SMTP server is not configured")
    if not 1 <= port <= 65535:
        raise NotificationConfigurationError("SMTP port must be between 1 and 65535")
    if security not in SMTP_SECURITY_OPTIONS:
        raise NotificationConfigurationError("SMTP security must be STARTTLS, SSL or NONE")
    if not valid_email(sender_email):
        raise NotificationConfigurationError("A valid sender email address is required")
    password = decrypt_smtp_password(setting_value(db, "notification_smtp_password"))
    if username and not password:
        raise NotificationConfigurationError("An SMTP password is required when a username is configured")
    return {
        "host": host,
        "port": port,
        "security": security,
        "username": username,
        "password": password,
        "sender_name": setting_value(db, "notification_sender_name").strip() or "Eaststone Training Matrix",
        "sender_email": sender_email,
    }


def _local_date(value: datetime) -> str:
    try:
        zone = ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    return as_utc(value).astimezone(zone).strftime("%d %b %Y")


def _assignment_lines(items: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(
            [
                f"- {item['document_code']} {item['version_label']} — {item['document_title']}",
                f"  Target date: {_local_date(item['due_at'])}",
            ]
        )
    return lines


def _assignment_payload(row) -> dict:
    assignment, _user, version, family = row
    return {
        "assignment_id": assignment.id,
        "document_code": family.code,
        "document_title": family.title,
        "version_label": version.version_label,
        "due_at": assignment.due_at,
        "assigned_at": assignment.assigned_at,
    }


def _new_assignment_message(user: User, items: list[dict]) -> tuple[str, str]:
    subject = "Training assigned" if len(items) > 1 else f"Training required: {items[0]['document_code']}"
    body = [
        f"Hello {user.display_name},",
        "",
        "The following training has been assigned to you:",
        "",
        *_assignment_lines(items),
        "",
        "Please sign in to Eaststone Training Matrix and complete the reading and acknowledgement by the target date shown above.",
        "",
        "Eaststone Training Matrix",
        "This is an automated notification.",
    ]
    return subject, "\n".join(body)


def _overdue_message(user: User, items: list[dict]) -> tuple[str, str]:
    subject = "Training overdue" if len(items) > 1 else f"Training overdue: {items[0]['document_code']}"
    body = [
        f"Hello {user.display_name},",
        "",
        "The following required training is overdue:",
        "",
        *_assignment_lines(items),
        "",
        "Please sign in to Eaststone Training Matrix and complete the overdue reading and acknowledgement as soon as possible.",
        "",
        "Eaststone Training Matrix",
        "This is an automated notification.",
    ]
    return subject, "\n".join(body)


def _compliance_message(user: User, result: dict, threshold: float) -> tuple[str, str]:
    subject = "Training compliance below required threshold"
    body = [
        f"Hello {user.display_name},",
        "",
        f"Your active training compliance is {result['compliance_percent']}%, below the required {threshold:g}% threshold.",
        f"Outstanding current SOP readings: {result['open']}",
        f"Overdue current SOP readings: {result['overdue']}",
        "",
        "Please sign in to Eaststone Training Matrix and complete your outstanding training. Overdue training should be completed as soon as possible.",
        "",
        "Eaststone Training Matrix",
        "This is an automated notification.",
    ]
    return subject, "\n".join(body)


def _queue_delivery(
    db: Session,
    *,
    notification_type: str,
    user: User | None,
    recipient_email: str,
    subject: str,
    body_text: str,
    dedupe_key: str,
    payload: dict | None = None,
) -> bool:
    if db.scalar(select(EmailNotificationDelivery.id).where(EmailNotificationDelivery.dedupe_key == dedupe_key)):
        return False
    db.add(
        EmailNotificationDelivery(
            notification_type=notification_type,
            user_id=user.id if user else None,
            recipient_email=recipient_email.strip(),
            subject=subject,
            body_text=body_text,
            status="PENDING",
            attempt_count=0,
            scheduled_for=utcnow(),
            dedupe_key=dedupe_key,
            payload_json=payload,
        )
    )
    return True


def _assignment_rows(db: Session):
    return db.execute(
        select(TrainingAssignment, User, DocumentVersion, DocumentFamily)
        .join(User, User.id == TrainingAssignment.user_id)
        .join(DocumentVersion, DocumentVersion.id == TrainingAssignment.document_version_id)
        .join(DocumentFamily, DocumentFamily.id == DocumentVersion.family_id)
        .where(
            TrainingAssignment.status == "ASSIGNED",
            User.is_active.is_(True),
            DocumentVersion.status == "RELEASED",
        )
        .order_by(User.id, TrainingAssignment.due_at, DocumentFamily.code)
    ).all()


def _enabled_since(db: Session) -> datetime:
    raw = setting_value(db, "notification_enabled_since")
    try:
        return as_utc(datetime.fromisoformat(raw)) if raw else utcnow()
    except ValueError:
        return utcnow()


def queue_assignment_and_overdue_notifications(db: Session) -> dict[str, int]:
    now = utcnow()
    cutover = _enabled_since(db)
    try:
        overdue_days = max(1, min(90, int(setting_value(db, "notification_overdue_frequency_days"))))
    except ValueError:
        overdue_days = 1
    new_by_user: dict[int, tuple[User, list[dict]]] = {}
    overdue_by_user: dict[int, tuple[User, list[dict]]] = {}
    for row in _assignment_rows(db):
        assignment, user, _version, _family = row
        assigned_at = as_utc(assignment.assigned_at)
        state = db.get(AssignmentNotificationState, assignment.id)
        if state is None:
            state = AssignmentNotificationState(
                assignment_id=assignment.id,
                assignment_assigned_at=assigned_at,
                assignment_notified_at=cutover if assigned_at < cutover else None,
            )
            db.add(state)
        elif as_utc(state.assignment_assigned_at) != assigned_at:
            state.assignment_assigned_at = assigned_at
            state.assignment_notified_at = cutover if assigned_at < cutover else None
            state.last_overdue_notified_at = None

        if not valid_email(user.email):
            continue
        item = _assignment_payload(row)
        if state.assignment_notified_at is None:
            new_by_user.setdefault(user.id, (user, []))[1].append(item)
        if as_utc(assignment.due_at) < now and (
            state.last_overdue_notified_at is None
            or as_utc(state.last_overdue_notified_at) + timedelta(days=overdue_days) <= now
        ):
            overdue_by_user.setdefault(user.id, (user, []))[1].append(item)

    queued_new = 0
    for user, items in new_by_user.values():
        fingerprint = hashlib.sha256(
            "|".join(f"{item['assignment_id']}:{as_utc(item['assigned_at']).isoformat()}" for item in items).encode()
        ).hexdigest()[:32]
        subject, body = _new_assignment_message(user, items)
        queued_new += int(
            _queue_delivery(
                db,
                notification_type="NEW_ASSIGNMENT",
                user=user,
                recipient_email=user.email or "",
                subject=subject,
                body_text=body,
                dedupe_key=f"NEW_ASSIGNMENT:{user.id}:{fingerprint}",
                payload={"assignment_ids": [item["assignment_id"] for item in items]},
            )
        )

    queued_overdue = 0
    for user, items in overdue_by_user.values():
        state_parts = []
        for item in items:
            state = db.get(AssignmentNotificationState, item["assignment_id"])
            previous = (
                as_utc(state.last_overdue_notified_at).isoformat()
                if state and state.last_overdue_notified_at
                else "never"
            )
            state_parts.append(f"{item['assignment_id']}:{previous}")
        fingerprint = hashlib.sha256("|".join(state_parts).encode()).hexdigest()[:32]
        subject, body = _overdue_message(user, items)
        queued_overdue += int(
            _queue_delivery(
                db,
                notification_type="OVERDUE",
                user=user,
                recipient_email=user.email or "",
                subject=subject,
                body_text=body,
                dedupe_key=f"OVERDUE:{user.id}:{fingerprint}",
                payload={"assignment_ids": [item["assignment_id"] for item in items]},
            )
        )
    return {"new_assignment": queued_new, "overdue": queued_overdue}


def _configured_threshold(db: Session) -> float:
    row = db.get(SystemSetting, "active_compliance_threshold_percent")
    try:
        return max(0.0, min(100.0, float(row.value))) if row else 80.0
    except (TypeError, ValueError):
        return 80.0


def _active_trainees(db: Session) -> list[User]:
    return (
        db.scalars(
            select(User)
            .join(UserJobRole, UserJobRole.user_id == User.id)
            .join(JobRole, JobRole.id == UserJobRole.job_role_id)
            .where(User.is_active.is_(True), JobRole.is_active.is_(True), active_role_condition())
            .order_by(User.display_name)
        )
        .unique()
        .all()
    )


def _compliance_for_users(db: Session, users: list[User]) -> dict[int, dict]:
    if not users:
        return {}
    current_version_ids = db.scalars(
        select(DocumentVersion.id)
        .join(DocumentFamily, DocumentFamily.id == DocumentVersion.family_id)
        .where(
            DocumentVersion.status == "RELEASED",
            DocumentFamily.is_active.is_(True),
            DocumentFamily.document_type == "SOP",
        )
    ).all()
    assignments = []
    if current_version_ids:
        assignments = db.scalars(
            select(TrainingAssignment).where(
                TrainingAssignment.user_id.in_([user.id for user in users]),
                TrainingAssignment.document_version_id.in_(current_version_ids),
                TrainingAssignment.status.in_(("ASSIGNED", "COMPLETED")),
            )
        ).all()
    by_user: dict[int, list[TrainingAssignment]] = defaultdict(list)
    for assignment in assignments:
        by_user[assignment.user_id].append(assignment)
    results: dict[int, dict] = {}
    for user in users:
        required = by_user[user.id]
        completed = sum(1 for item in required if item.status == "COMPLETED")
        open_items = [item for item in required if item.status == "ASSIGNED"]
        overdue = sum(1 for item in open_items if displayed_status(item) == "OVERDUE")
        total = len(required)
        results[user.id] = {
            "compliance_percent": round(completed / total * 100, 1) if total else 100.0,
            "open": len(open_items),
            "overdue": overdue,
        }
    return results


def queue_compliance_notifications(db: Session) -> int:
    threshold = _configured_threshold(db)
    users = _active_trainees(db)
    results = _compliance_for_users(db, users)
    queued = 0
    for user in users:
        result = results[user.id]
        below = result["compliance_percent"] < threshold
        state = db.get(ComplianceNotificationState, user.id)
        if state is None:
            state = ComplianceNotificationState(user_id=user.id, was_below_threshold=False)
            db.add(state)
        transitioned_below = below and not state.was_below_threshold
        state.last_compliance_percent = str(result["compliance_percent"])
        state.last_threshold_percent = str(threshold)
        if not below:
            state.was_below_threshold = False
        elif transitioned_below and valid_email(user.email):
            subject, body = _compliance_message(user, result, threshold)
            fingerprint = hashlib.sha256(
                f"{user.id}|{threshold}|{result['compliance_percent']}|{utcnow().date().isoformat()}".encode()
            ).hexdigest()[:32]
            created = _queue_delivery(
                db,
                notification_type="BELOW_THRESHOLD",
                user=user,
                recipient_email=user.email or "",
                subject=subject,
                body_text=body,
                dedupe_key=f"BELOW_THRESHOLD:{user.id}:{fingerprint}",
                payload={"compliance_user_id": user.id},
            )
            if created:
                state.was_below_threshold = True
                queued += 1
    return queued


def _send_email(configuration: dict, *, recipient: str, subject: str, body_text: str) -> None:
    message = EmailMessage()
    message["From"] = formataddr((configuration["sender_name"], configuration["sender_email"]))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body_text)
    context = ssl.create_default_context()
    if configuration["security"] == "SSL":
        client = smtplib.SMTP_SSL(configuration["host"], configuration["port"], timeout=15, context=context)
    else:
        client = smtplib.SMTP(configuration["host"], configuration["port"], timeout=15)
    with client:
        client.ehlo()
        if configuration["security"] == "STARTTLS":
            client.starttls(context=context)
            client.ehlo()
        if configuration["username"]:
            client.login(configuration["username"], configuration["password"])
        client.send_message(message)


def _apply_delivery_success(db: Session, delivery: EmailNotificationDelivery, sent_at: datetime) -> None:
    payload = delivery.payload_json or {}
    assignment_ids = payload.get("assignment_ids", [])
    if delivery.notification_type == "NEW_ASSIGNMENT":
        for assignment_id in assignment_ids:
            state = db.get(AssignmentNotificationState, int(assignment_id))
            if state:
                state.assignment_notified_at = sent_at
    elif delivery.notification_type == "OVERDUE":
        for assignment_id in assignment_ids:
            state = db.get(AssignmentNotificationState, int(assignment_id))
            if state:
                state.last_overdue_notified_at = sent_at
    elif delivery.notification_type == "BELOW_THRESHOLD" and delivery.user_id:
        state = db.get(ComplianceNotificationState, delivery.user_id)
        if state:
            state.last_notified_at = sent_at


def process_pending_deliveries(db: Session, *, force: bool = False) -> dict[str, int]:
    configuration = smtp_configuration(db)
    now = utcnow()
    query = select(EmailNotificationDelivery).where(
        EmailNotificationDelivery.status.in_(("PENDING", "FAILED")),
        EmailNotificationDelivery.attempt_count < MAX_DELIVERY_ATTEMPTS,
    )
    if not force:
        query = query.where(EmailNotificationDelivery.scheduled_for <= now)
    deliveries = db.scalars(query.order_by(EmailNotificationDelivery.scheduled_for).limit(DELIVERY_BATCH_SIZE)).all()
    sent = 0
    failed = 0
    for delivery in deliveries:
        delivery.attempt_count += 1
        delivery.last_attempt_at = utcnow()
        try:
            _send_email(
                configuration,
                recipient=delivery.recipient_email,
                subject=delivery.subject,
                body_text=delivery.body_text,
            )
        except Exception as exc:
            delivery.status = "FAILED"
            delivery.error_message = str(exc)[:2000]
            retry_minutes = min(1440, 5 * (2 ** min(delivery.attempt_count - 1, 8)))
            delivery.scheduled_for = utcnow() + timedelta(minutes=retry_minutes)
            record_audit(
                db,
                event_type="EMAIL_NOTIFICATION_FAILED",
                actor_username="SYSTEM",
                entity_type="EMAIL_NOTIFICATION",
                entity_id=delivery.id,
                success=False,
                reason="SMTP delivery attempt failed",
                metadata={
                    "notification_type": delivery.notification_type,
                    "recipient": delivery.recipient_email,
                    "attempt_count": delivery.attempt_count,
                    "retry_after": delivery.scheduled_for,
                    "error": delivery.error_message,
                },
            )
            failed += 1
        else:
            sent_at = utcnow()
            delivery.status = "SENT"
            delivery.sent_at = sent_at
            delivery.error_message = None
            _apply_delivery_success(db, delivery, sent_at)
            record_audit(
                db,
                event_type="EMAIL_NOTIFICATION_SENT",
                actor_username="SYSTEM",
                entity_type="EMAIL_NOTIFICATION",
                entity_id=delivery.id,
                reason="Configured training notification delivered",
                metadata={
                    "notification_type": delivery.notification_type,
                    "recipient": delivery.recipient_email,
                    "attempt_count": delivery.attempt_count,
                },
            )
            sent += 1
        db.commit()
    return {"sent": sent, "failed": failed}


def run_notification_cycle(db: Session, *, force: bool = False) -> dict:
    if not email_enabled(db):
        return {"enabled": False, "queued": 0, "sent": 0, "failed": 0}
    smtp_configuration(db)
    assignment_counts = queue_assignment_and_overdue_notifications(db)
    compliance_count = queue_compliance_notifications(db)
    db.commit()
    delivery_counts = process_pending_deliveries(db, force=force)
    return {
        "enabled": True,
        "queued": sum(assignment_counts.values()) + compliance_count,
        "queued_by_type": {**assignment_counts, "below_threshold": compliance_count},
        **delivery_counts,
    }


def send_test_notification(db: Session, *, recipient_email: str, requested_by: User) -> EmailNotificationDelivery:
    if not valid_email(recipient_email):
        raise NotificationConfigurationError("Enter a valid test recipient email address")
    configuration = smtp_configuration(db)
    now = utcnow()
    delivery = EmailNotificationDelivery(
        notification_type="TEST",
        user_id=requested_by.id,
        recipient_email=recipient_email.strip(),
        subject="Eaststone Training Matrix email test",
        body_text=(
            f"Hello {requested_by.display_name},\n\n"
            "This confirms that email notifications from Eaststone Training Matrix are configured correctly.\n\n"
            "Eaststone Training Matrix\nThis is an automated notification."
        ),
        status="PENDING",
        attempt_count=1,
        scheduled_for=now,
        last_attempt_at=now,
        dedupe_key=f"TEST:{requested_by.id}:{now.timestamp()}",
        payload_json={"requested_by": requested_by.username},
    )
    db.add(delivery)
    db.flush()
    try:
        _send_email(
            configuration,
            recipient=delivery.recipient_email,
            subject=delivery.subject,
            body_text=delivery.body_text,
        )
    except Exception as exc:
        delivery.status = "FAILED"
        delivery.error_message = str(exc)[:2000]
        record_audit(
            db,
            event_type="EMAIL_NOTIFICATION_TEST_FAILED",
            actor=requested_by,
            entity_type="EMAIL_NOTIFICATION",
            entity_id=delivery.id,
            success=False,
            reason="Administrator requested SMTP configuration test",
            metadata={"recipient": delivery.recipient_email, "error": delivery.error_message},
        )
    else:
        delivery.status = "SENT"
        delivery.sent_at = utcnow()
        record_audit(
            db,
            event_type="EMAIL_NOTIFICATION_TEST_SENT",
            actor=requested_by,
            entity_type="EMAIL_NOTIFICATION",
            entity_id=delivery.id,
            reason="Administrator requested SMTP configuration test",
            metadata={"recipient": delivery.recipient_email},
        )
    db.commit()
    return delivery
