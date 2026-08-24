from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import runtime
from ..models import BackupRun, DocumentFamily, DocumentVersion

SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_.-]+\.dump$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connection_parts(url: str | None = None) -> dict[str, str]:
    parsed = urlparse((url or runtime.url).replace("postgresql+psycopg", "postgresql", 1))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("Backup and restore require PostgreSQL")
    return {
        "host": parsed.hostname or "db",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }


def postgres_env(parts: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = parts["password"]
    return env


def source_inventory(db: Session) -> list[dict]:
    rows = (
        db.execute(
            select(
                DocumentFamily.code,
                DocumentFamily.title,
                DocumentVersion.version_label,
                DocumentVersion.status,
                DocumentVersion.relative_path,
                DocumentVersion.source_sha256,
                DocumentVersion.source_size,
            ).join(DocumentVersion, DocumentVersion.family_id == DocumentFamily.id)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def create_backup(
    db: Session,
    *,
    backup_type: str,
    reason: str,
    created_by: int | None,
) -> BackupRun:
    parts = connection_parts()
    timestamp = utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    safe_type = re.sub(r"[^A-Z0-9_-]", "_", backup_type.upper())
    filename = f"training_matrix_{timestamp}_{safe_type}.dump"
    path = settings.backup_root / filename
    run = BackupRun(
        filename=filename,
        backup_type=safe_type,
        status="RUNNING",
        database_name=parts["database"],
        reason=reason,
        created_by=created_by,
    )
    db.add(run)
    db.commit()
    try:
        result = subprocess.run(
            [
                "pg_dump",
                "--host",
                parts["host"],
                "--port",
                parts["port"],
                "--username",
                parts["user"],
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(path),
                parts["database"],
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
            env=postgres_env(parts),
        )
        if result.returncode != 0 or not path.exists():
            raise RuntimeError((result.stderr or "pg_dump failed")[-2000:])
        digest = sha256_file(path)
        manifest = {
            "application": settings.app_name,
            "app_version": settings.app_version,
            "created_at": utcnow().isoformat(),
            "created_by": created_by,
            "backup_type": safe_type,
            "reason": reason,
            "database_name": parts["database"],
            "dump_filename": filename,
            "dump_sha256": digest,
            "dump_size_bytes": path.stat().st_size,
            "documents_storage": "EXTERNAL_SHARED_FOLDER_NOT_INCLUDED",
            "document_inventory": source_inventory(db),
        }
        path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        run.status = "COMPLETE"
        run.sha256 = digest
        run.size_bytes = path.stat().st_size
        run.completed_at = utcnow()
    except Exception as exc:
        run.status = "FAILED"
        run.error_message = str(exc)[:4000]
        run.completed_at = utcnow()
    db.commit()
    return run


def list_backup_files() -> list[dict]:
    results = []
    for path in sorted(
        settings.backup_root.glob("*.dump"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        if not SAFE_FILENAME.fullmatch(path.name):
            continue
        manifest_path = path.with_suffix(".manifest.json")
        manifest = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                manifest = None
        results.append(
            {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                "manifest": manifest,
            }
        )
    return results


def safe_backup_path(filename: str) -> Path:
    if not SAFE_FILENAME.fullmatch(filename):
        raise ValueError("Invalid backup filename")
    path = (settings.backup_root / filename).resolve()
    path.relative_to(settings.backup_root.resolve())
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    return path


def verify_backup(filename: str) -> dict:
    path = safe_backup_path(filename)
    manifest_path = path.with_suffix(".manifest.json")
    actual = sha256_file(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    hash_ok = manifest is None or manifest.get("dump_sha256") == actual
    parts = connection_parts()
    result = subprocess.run(
        ["pg_restore", "--list", str(path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=postgres_env(parts),
    )
    return {
        "filename": filename,
        "sha256": actual,
        "manifest_present": manifest is not None,
        "hash_ok": hash_ok,
        "pg_restore_readable": result.returncode == 0,
        "valid": hash_ok and result.returncode == 0,
        "error": result.stderr[-1000:] if result.returncode else None,
    }


def prune_automatic_backups(retention_days: int) -> list[str]:
    cutoff = utcnow() - timedelta(days=retention_days)
    removed = []
    for path in settings.backup_root.glob("training_matrix_*_AUTOMATIC.dump"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            manifest = path.with_suffix(".manifest.json")
            path.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


def restore_into_new_dataset(filename: str, *, set_by: str) -> dict:
    verification = verify_backup(filename)
    if not verification["valid"]:
        raise RuntimeError("Backup verification failed; restore was not started")
    path = safe_backup_path(filename)
    parts = connection_parts()
    dataset = f"training_restore_{utcnow().strftime('%Y%m%d_%H%M%S')}"
    target_url = runtime.url_for_database(dataset)
    create_result = subprocess.run(
        [
            "createdb",
            "--host",
            parts["host"],
            "--port",
            parts["port"],
            "--username",
            parts["user"],
            dataset,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=postgres_env(parts),
    )
    if create_result.returncode != 0:
        raise RuntimeError(f"Could not create staged restore dataset: {create_result.stderr[-1500:]}")
    restore_result = subprocess.run(
        [
            "pg_restore",
            "--host",
            parts["host"],
            "--port",
            parts["port"],
            "--username",
            parts["user"],
            "--dbname",
            dataset,
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
        env=postgres_env(parts),
    )
    if restore_result.returncode != 0:
        raise RuntimeError(f"Restore failed in staged dataset {dataset}: {restore_result.stderr[-2000:]}")
    engine = create_engine(target_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            users = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
            documents = connection.execute(text("SELECT count(*) FROM document_families")).scalar_one()
            audit = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
    finally:
        engine.dispose()
    runtime.activate(dataset, set_by=set_by)
    return {
        "activated_dataset": dataset,
        "source_backup": filename,
        "sanity": {"users": users, "documents": documents, "audit_events": audit},
        "previous_dataset_retained": True,
    }
