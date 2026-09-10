from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..database import get_db
from ..models import SystemSetting
from ..schemas import SettingsPatch
from ..security import AuthContext, require_permission

router = APIRouter(prefix="/admin/system", tags=["System Administration"])

ALLOWED_SETTINGS = {
    "backup_time",
    "backup_timezone",
    "backup_retention_days",
    "training_default_due_days",
    "active_compliance_threshold_percent",
    "session_idle_minutes",
    "session_absolute_minutes",
    "acknowledgement_statement",
    "source_scan_interval_minutes",
}


def _current_value(db: Session, key: str, fallback: str) -> str:
    item = db.get(SystemSetting, key)
    return item.value if item else fallback


@router.patch("/extended-settings")
def patch_extended_settings(
    payload: SettingsPatch,
    request: Request,
    auth: AuthContext = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    unknown = set(payload.values) - ALLOWED_SETTINGS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported settings: {', '.join(sorted(unknown))}",
        )

    try:
        for key, value in payload.values.items():
            if key == "backup_time":
                time.fromisoformat(value)
            elif key == "backup_timezone":
                ZoneInfo(value)
            elif key == "backup_retention_days" and not 1 <= int(value) <= 3650:
                raise ValueError("must be between 1 and 3650")
            elif key == "training_default_due_days" and not 0 <= int(value) <= 3650:
                raise ValueError("must be between 0 and 3650")
            elif key == "active_compliance_threshold_percent" and not 0 <= float(value) <= 100:
                raise ValueError("must be between 0 and 100")
            elif key == "session_idle_minutes" and not 5 <= int(value) <= 240:
                raise ValueError("must be between 5 and 240 minutes")
            elif key == "session_absolute_minutes" and not 15 <= int(value) <= 1440:
                raise ValueError("must be between 15 and 1440 minutes")
            elif key == "acknowledgement_statement" and not 10 <= len(value.strip()) <= 2000:
                raise ValueError("must contain 10 to 2000 characters")
            elif key == "source_scan_interval_minutes" and not 5 <= int(value) <= 1440:
                raise ValueError("must be between 5 and 1440")
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {key}: {exc}") from exc

    idle = int(payload.values.get("session_idle_minutes", _current_value(db, "session_idle_minutes", "15")))
    absolute = int(
        payload.values.get(
            "session_absolute_minutes",
            _current_value(db, "session_absolute_minutes", "480"),
        )
    )
    if idle >= absolute:
        raise HTTPException(
            status_code=400,
            detail="Session maximum duration must be longer than the inactivity timeout",
        )

    before: dict[str, str | None] = {}
    after: dict[str, str] = {}
    for key, value in payload.values.items():
        setting = db.get(SystemSetting, key)
        before[key] = setting.value if setting else None
        if setting is None:
            setting = SystemSetting(key=key, value=value, updated_by=auth.user.id)
            db.add(setting)
        else:
            setting.value = value
            setting.updated_by = auth.user.id
        after[key] = value

    record_audit(
        db,
        event_type="SYSTEM_SETTINGS_UPDATED",
        request=request,
        actor=auth,
        entity_type="SYSTEM_SETTINGS",
        entity_id="GLOBAL",
        reason=payload.reason,
        before=before,
        after=after,
    )
    db.commit()
    return {"ok": True}
