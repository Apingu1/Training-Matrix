from __future__ import annotations

import os
import shutil
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..database import get_db, runtime
from ..models import SystemSetting
from ..schemas import BackupCreateRequest, RestoreRequest, SettingsPatch
from ..security import AuthContext, require_permission
from ..services.backup import (
    SAFE_FILENAME,
    create_backup,
    list_backup_files,
    restore_into_new_dataset,
    safe_backup_path,
    verify_backup,
)
from ..services.file_source import source_status

router = APIRouter(prefix="/admin/system", tags=["System Administration"])


@router.get("/info")
def system_info(
    _: AuthContext = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "database_name": runtime.database_name,
        "document_source": source_status(),
        "backup_path": str(settings.backup_root),
        "settings": {item.key: item.value for item in db.scalars(select(SystemSetting)).all()},
    }


@router.get("/settings")
def list_settings(
    _: AuthContext = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    return [
        {
            "key": item.key,
            "value": item.value,
            "description": item.description,
            "updated_at": item.updated_at,
        }
        for item in db.scalars(select(SystemSetting).order_by(SystemSetting.key)).all()
    ]


@router.patch("/settings")
def patch_settings(
    payload: SettingsPatch,
    request: Request,
    auth: AuthContext = Depends(require_permission("settings.manage")),
    db: Session = Depends(get_db),
):
    allowed = {
        "maintenance_mode",
        "backup_time",
        "backup_timezone",
        "backup_retention_days",
        "training_default_due_days",
        "acknowledgement_statement",
    }
    unknown = set(payload.values) - allowed
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported settings: {', '.join(sorted(unknown))}",
        )
    for key, value in payload.values.items():
        try:
            if key == "maintenance_mode" and value.lower() not in {"true", "false"}:
                raise ValueError("must be true or false")
            if key == "backup_time":
                time.fromisoformat(value)
            if key == "backup_timezone":
                ZoneInfo(value)
            if key == "backup_retention_days" and not 1 <= int(value) <= 3650:
                raise ValueError("must be between 1 and 3650")
            if key == "training_default_due_days" and not 0 <= int(value) <= 3650:
                raise ValueError("must be between 0 and 3650")
            if key == "acknowledgement_statement" and not 10 <= len(value.strip()) <= 2000:
                raise ValueError("must contain 10 to 2000 characters")
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {key}: {exc}") from exc
    before = {}
    after = {}
    for key, value in payload.values.items():
        setting = db.get(SystemSetting, key)
        if setting is None:
            setting = SystemSetting(key=key, value=value, updated_by=auth.user.id)
            db.add(setting)
            before[key] = None
        else:
            before[key] = setting.value
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


@router.get("/backups")
def backups(
    _: AuthContext = Depends(require_permission("backups.manage")),
):
    return list_backup_files()


@router.post("/backups", status_code=201)
def manual_backup(
    payload: BackupCreateRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("backups.manage")),
    db: Session = Depends(get_db),
):
    run = create_backup(db, backup_type="MANUAL", reason=payload.reason, created_by=auth.user.id)
    record_audit(
        db,
        event_type="BACKUP_CREATED" if run.status == "COMPLETE" else "BACKUP_FAILED",
        request=request,
        actor=auth,
        entity_type="BACKUP",
        entity_id=run.id,
        reason=payload.reason,
        success=run.status == "COMPLETE",
        after={
            "filename": run.filename,
            "sha256": run.sha256,
            "size_bytes": run.size_bytes,
            "status": run.status,
        },
    )
    db.commit()
    if run.status != "COMPLETE":
        raise HTTPException(status_code=500, detail=run.error_message or "Backup failed")
    return {
        "filename": run.filename,
        "sha256": run.sha256,
        "size_bytes": run.size_bytes,
    }


@router.get("/backups/{filename}/verify")
def verify_backup_file(
    filename: str,
    _: AuthContext = Depends(require_permission("backups.manage")),
):
    try:
        return verify_backup(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/backups/{filename}/download")
def download_backup(
    filename: str,
    _: AuthContext = Depends(require_permission("backups.manage")),
):
    try:
        path = safe_backup_path(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/backups/upload", status_code=201)
def upload_backup(
    request: Request,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_permission("backups.manage")),
    db: Session = Depends(get_db),
):
    filename = Path(file.filename or "").name
    if not SAFE_FILENAME.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Select a PostgreSQL custom-format .dump file")
    target = settings.backup_root / filename
    if target.exists():
        raise HTTPException(status_code=409, detail="A backup with that filename already exists")
    temporary = settings.backup_root / f".{filename}.uploading"
    try:
        with temporary.open("wb") as output:
            shutil.copyfileobj(file.file, output, length=1024 * 1024)
        if temporary.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded backup is empty")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    record_audit(
        db,
        event_type="BACKUP_UPLOADED",
        request=request,
        actor=auth,
        entity_type="BACKUP",
        entity_id=filename,
        reason="Backup uploaded for controlled verification or restore",
        after={"filename": filename, "size_bytes": target.stat().st_size},
    )
    db.commit()
    return {
        "filename": filename,
        "size_bytes": target.stat().st_size,
        "uploaded_by": auth.user.username,
    }


@router.post("/restore")
def restore_backup(
    payload: RestoreRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("backups.manage")),
    db: Session = Depends(get_db),
):
    maintenance = db.get(SystemSetting, "maintenance_mode")
    if not maintenance or maintenance.value.lower() != "true":
        raise HTTPException(status_code=409, detail="Enable maintenance mode before restoring a backup")
    if payload.confirmation != f"RESTORE {payload.filename}":
        raise HTTPException(status_code=400, detail=f"Enter exactly: RESTORE {payload.filename}")
    pre_restore = create_backup(
        db,
        backup_type="PRE_RESTORE",
        reason=f"Automatic safety backup before restore: {payload.reason}",
        created_by=auth.user.id,
    )
    if pre_restore.status != "COMPLETE":
        raise HTTPException(
            status_code=500,
            detail="Pre-restore safety backup failed; restore was cancelled",
        )
    record_audit(
        db,
        event_type="RESTORE_STARTED",
        request=request,
        actor=auth,
        entity_type="BACKUP",
        entity_id=payload.filename,
        reason=payload.reason,
        metadata={
            "pre_restore_backup": pre_restore.filename,
            "current_dataset": runtime.database_name,
        },
    )
    db.commit()
    previous_dataset = runtime.database_name
    try:
        result = restore_into_new_dataset(payload.filename, set_by=auth.user.username)
    except Exception as exc:
        record_audit(
            db,
            event_type="RESTORE_FAILED",
            request=request,
            actor=auth,
            entity_type="BACKUP",
            entity_id=payload.filename,
            reason=str(exc),
            success=False,
        )
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    with runtime.session() as restored_db:
        record_audit(
            restored_db,
            event_type="RESTORE_ACTIVATED",
            request=request,
            actor_username=auth.user.username,
            entity_type="DATASET",
            entity_id=result["activated_dataset"],
            reason=payload.reason,
            metadata={
                **result,
                "previous_dataset": previous_dataset,
                "pre_restore_backup": pre_restore.filename,
            },
        )
        restored_db.commit()
    return result
