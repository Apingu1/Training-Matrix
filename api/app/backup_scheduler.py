from __future__ import annotations

import fcntl
import time
from datetime import datetime, timezone
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .database import runtime
from .models import AuditEvent, BackupRun, SystemSetting
from .services.backup import create_backup, prune_automatic_backups


def setting(db, key: str, default: str) -> str:
    row = db.get(SystemSetting, key)
    return row.value if row else default


def already_backed_up_today(db, local_now: datetime) -> bool:
    start_local = datetime.combine(local_now.date(), clock_time.min, tzinfo=local_now.tzinfo)
    start_utc = start_local.astimezone(timezone.utc)
    return (
        db.scalar(
            select(BackupRun.id)
            .where(
                BackupRun.backup_type == "AUTOMATIC",
                BackupRun.status == "COMPLETE",
                BackupRun.created_at >= start_utc,
            )
            .limit(1)
        )
        is not None
    )


def run_once() -> None:
    runtime.refresh_from_runtime_file()
    with runtime.session() as db:
        timezone_name = setting(db, "backup_timezone", "Europe/London")
        configured = setting(db, "backup_time", "02:30")
        retention = int(setting(db, "backup_retention_days", "30"))
        try:
            hour, minute = (int(part) for part in configured.split(":", 1))
            scheduled = clock_time(hour=hour, minute=minute)
            zone = ZoneInfo(timezone_name)
        except (ValueError, KeyError):
            return
        local_now = datetime.now(zone)
        if local_now.time().replace(second=0, microsecond=0) < scheduled or already_backed_up_today(db, local_now):
            return
        run = create_backup(
            db,
            backup_type="AUTOMATIC",
            reason=f"Scheduled daily backup at {configured} {timezone_name}",
            created_by=None,
        )
        removed = prune_automatic_backups(retention)
        db.add(
            AuditEvent(
                event_type="AUTOMATIC_BACKUP_COMPLETED" if run.status == "COMPLETE" else "AUTOMATIC_BACKUP_FAILED",
                entity_type="BACKUP",
                entity_id=str(run.id),
                actor_username="SYSTEM",
                success=run.status == "COMPLETE",
                reason=run.error_message,
                metadata_json={"filename": run.filename, "retention_removed": removed},
            )
        )
        db.commit()


def main() -> None:
    lock_path = "/runtime/automatic-backup.lock"
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        while True:
            try:
                run_once()
            except Exception:
                pass
            time.sleep(30)


if __name__ == "__main__":
    main()
