from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..database import get_db
from ..models import ComplianceNotificationState, EmailNotificationDelivery, SystemSetting
from ..schemas import NotificationSettingsUpdate, NotificationTestRequest
from ..security import AuthContext, require_permission, utcnow
from ..services.notifications import (
    NotificationConfigurationError,
    email_enabled,
    encrypt_smtp_password,
    public_notification_settings,
    run_notification_cycle,
    send_test_notification,
    valid_email,
)

router = APIRouter(prefix="/admin/notifications", tags=["Email Notifications"])

PUBLIC_SETTING_MAP = {
    "notification_email_enabled": "enabled",
    "notification_smtp_host": "smtp_host",
    "notification_smtp_port": "smtp_port",
    "notification_smtp_security": "smtp_security",
    "notification_smtp_username": "smtp_username",
    "notification_sender_name": "sender_name",
    "notification_sender_email": "sender_email",
    "notification_overdue_frequency_days": "overdue_frequency_days",
}


def _set_setting(db: Session, key: str, value: str, *, updated_by: int) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=updated_by))
    else:
        row.value = value
        row.updated_by = updated_by


def _delivery_dict(delivery: EmailNotificationDelivery) -> dict:
    return {
        "id": delivery.id,
        "notification_type": delivery.notification_type,
        "user_id": delivery.user_id,
        "recipient_email": delivery.recipient_email,
        "subject": delivery.subject,
        "status": delivery.status,
        "attempt_count": delivery.attempt_count,
        "scheduled_for": delivery.scheduled_for,
        "last_attempt_at": delivery.last_attempt_at,
        "sent_at": delivery.sent_at,
        "error_message": delivery.error_message,
        "created_at": delivery.created_at,
    }


@router.get("/settings")
def get_notification_settings(
    _: AuthContext = Depends(require_permission("notifications.manage")),
    db: Session = Depends(get_db),
):
    return public_notification_settings(db)


@router.patch("/settings")
def update_notification_settings(
    payload: NotificationSettingsUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("notifications.manage")),
    db: Session = Depends(get_db),
):
    if payload.sender_email and not valid_email(payload.sender_email):
        raise HTTPException(status_code=400, detail="Enter a valid sender email address")
    if payload.enabled and not payload.smtp_host.strip():
        raise HTTPException(status_code=400, detail="An SMTP server is required before notifications can be enabled")
    if payload.enabled and not valid_email(payload.sender_email):
        raise HTTPException(
            status_code=400, detail="A valid sender email is required before notifications can be enabled"
        )

    existing_password = db.get(SystemSetting, "notification_smtp_password")
    password_configured = bool(existing_password and existing_password.value)
    if payload.clear_smtp_password:
        password_configured = False
    if payload.smtp_password:
        password_configured = True
    if payload.enabled and payload.smtp_username.strip() and not password_configured:
        raise HTTPException(
            status_code=400,
            detail="Enter an SMTP password when an authenticated SMTP username is used",
        )

    before = public_notification_settings(db)
    previously_enabled = email_enabled(db)
    values = {
        "notification_email_enabled": str(payload.enabled).lower(),
        "notification_smtp_host": payload.smtp_host.strip(),
        "notification_smtp_port": str(payload.smtp_port),
        "notification_smtp_security": payload.smtp_security,
        "notification_smtp_username": payload.smtp_username.strip(),
        "notification_sender_name": payload.sender_name.strip(),
        "notification_sender_email": payload.sender_email.strip(),
        "notification_overdue_frequency_days": str(payload.overdue_frequency_days),
    }
    for key, value in values.items():
        _set_setting(db, key, value, updated_by=auth.user.id)
    if payload.clear_smtp_password:
        _set_setting(db, "notification_smtp_password", "", updated_by=auth.user.id)
    elif payload.smtp_password:
        _set_setting(
            db,
            "notification_smtp_password",
            encrypt_smtp_password(payload.smtp_password),
            updated_by=auth.user.id,
        )

    if payload.enabled and not previously_enabled:
        _set_setting(db, "notification_enabled_since", utcnow().isoformat(), updated_by=auth.user.id)
        for state in db.scalars(select(ComplianceNotificationState)).all():
            state.was_below_threshold = False

    smtp_changed = any(
        str(before.get(PUBLIC_SETTING_MAP[key], "")) != value
        for key, value in values.items()
        if key.startswith("notification_smtp_") or key in {"notification_sender_name", "notification_sender_email"}
    ) or bool(payload.smtp_password or payload.clear_smtp_password)
    if smtp_changed:
        for delivery in db.scalars(
            select(EmailNotificationDelivery).where(EmailNotificationDelivery.status == "FAILED")
        ).all():
            delivery.attempt_count = 0
            delivery.scheduled_for = utcnow()

    db.flush()
    after = public_notification_settings(db)
    record_audit(
        db,
        event_type="EMAIL_NOTIFICATION_SETTINGS_UPDATED",
        request=request,
        actor=auth,
        entity_type="EMAIL_NOTIFICATION_SETTINGS",
        entity_id="GLOBAL",
        reason=payload.reason,
        before=before,
        after=after,
        metadata={
            "smtp_password_changed": bool(payload.smtp_password),
            "smtp_password_cleared": payload.clear_smtp_password,
        },
    )
    db.commit()
    return after


@router.get("/deliveries")
def list_deliveries(
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthContext = Depends(require_permission("notifications.manage")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(EmailNotificationDelivery).order_by(EmailNotificationDelivery.created_at.desc()).limit(limit)
    ).all()
    return [_delivery_dict(row) for row in rows]


@router.post("/test")
def test_notification(
    payload: NotificationTestRequest,
    auth: AuthContext = Depends(require_permission("notifications.manage")),
    db: Session = Depends(get_db),
):
    try:
        delivery = send_test_notification(db, recipient_email=payload.recipient_email, requested_by=auth.user)
    except NotificationConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if delivery.status != "SENT":
        raise HTTPException(status_code=502, detail=delivery.error_message or "The SMTP test email could not be sent")
    return _delivery_dict(delivery)


@router.post("/run")
def run_notifications_now(
    request: Request,
    auth: AuthContext = Depends(require_permission("notifications.manage")),
    db: Session = Depends(get_db),
):
    try:
        result = run_notification_cycle(db, force=True)
    except NotificationConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit(
        db,
        event_type="EMAIL_NOTIFICATION_CYCLE_REQUESTED",
        request=request,
        actor=auth,
        entity_type="EMAIL_NOTIFICATION",
        entity_id="MANUAL_CYCLE",
        reason="Administrator requested immediate notification processing",
        metadata=result,
    )
    db.commit()
    return result
