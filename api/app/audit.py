from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .models import AuditEvent, User
from .security import AuthContext, client_ip


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(v) for v in value]
    return value


def model_snapshot(instance: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {
        attr.key: json_value(getattr(instance, attr.key))
        for attr in inspect(instance).mapper.column_attrs
        if attr.key not in excluded
    }


def record_audit(
    db: Session,
    *,
    event_type: str,
    request: Request | None = None,
    actor: AuthContext | User | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    success: bool = True,
    reason: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
    actor_username: str | None = None,
) -> AuditEvent:
    if isinstance(actor, AuthContext):
        actor_user = actor.user
    else:
        actor_user = actor
    event = AuditEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_user_id=actor_user.id if actor_user else None,
        actor_username=actor_user.username if actor_user else actor_username,
        success=success,
        reason=reason,
        before_json=json_value(before),
        after_json=json_value(after),
        metadata_json=json_value(metadata),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500] if request else None,
        request_id=getattr(request.state, "request_id", None) if request else None,
    )
    db.add(event)
    db.flush()
    return event
