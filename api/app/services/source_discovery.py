from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocumentFamily, DocumentVersion, SourceInventoryFile, SourceScanRun
from .file_source import ALLOWED_EXTENSIONS, sha256_file, source_root

MAX_INVENTORY_FILES = 50_000
_scan_lock = threading.Lock()

_STANDARD_CODE = re.compile(
    r"(?i)\b(ES[._ -](?:SOP|COM|QF|ED|LOG(?:BOOK)?|FORM|FRM|AB|MISC)"
    r"(?:[._ -][A-Z]{2,10})?[._ -]\d{1,5}(?:[._ -]F\d{1,4})?)\b"
)
_SHORT_SOP_CODE = re.compile(r"(?i)\b(SOP[._ -]\d{1,5}(?:[._ -]F\d{1,4})?)\b")
_GENERIC_CODE = re.compile(r"(?i)\b(ES(?:[._ -][A-Z0-9]{1,12}){2,5})\b")
_VERSION = re.compile(r"(?i)(?:^|[._ -])V(?:ER(?:SION)?)?[._ -]?(\d{1,4})(?=$|[._ -])")

_DEPARTMENTS = {
    "production": "Production",
    "manufacturing": "Production",
    "quality assurance": "Quality Assurance",
    "qa": "Quality Assurance",
    "quality control": "Quality Control",
    "qc": "Quality Control",
    "warehouse": "Warehouse",
    "engineering": "Engineering",
    "r&d": "Research & Development",
    "research and development": "Research & Development",
    "it": "Information Technology",
    "hr": "Human Resources",
    "regulatory": "Regulatory Affairs",
    "customer service": "Customer Service",
}


@dataclass(frozen=True, slots=True)
class InferredMetadata:
    code: str | None
    version: str | None
    title: str
    document_type: str
    owner_department: str | None


def _normalise_code(value: str) -> str:
    return re.sub(r"[ _-]+", ".", value.strip()).upper().strip(".")


def _normalise_detected_code(value: str) -> str:
    code = _normalise_code(value)
    if code.startswith("SOP."):
        code = f"ES.{code}"
    return code


def _document_type(code: str | None, path: Path) -> str:
    upper_code = code or ""
    combined = " ".join(part.lower() for part in path.parts)
    if re.search(r"\.F\d{1,4}$", upper_code) or re.search(r"\bforms?\b", combined):
        return "FORM"
    if ".SOP." in f".{upper_code}.":
        return "SOP"
    if ".COM." in f".{upper_code}.":
        return "COM"
    if ".QF." in f".{upper_code}.":
        return "QF"
    if ".ED." in f".{upper_code}.":
        return "ED"
    if ".LOG." in f".{upper_code}." or "log book" in combined or "logbook" in combined:
        return "LOG_BOOK"
    if "awareness" in combined:
        return "AWARENESS_BRIEF"
    return "MISC"


def _department(path: Path) -> str | None:
    for part in path.parts[:-1]:
        cleaned = re.sub(r"[._-]+", " ", part).strip().lower()
        if cleaned in _DEPARTMENTS:
            return _DEPARTMENTS[cleaned]
    return None


def infer_metadata(relative_path: str) -> InferredMetadata:
    path = Path(relative_path)
    stem = path.stem
    code_match = _STANDARD_CODE.search(stem)
    if not code_match:
        for part in reversed(path.parts[:-1]):
            code_match = _STANDARD_CODE.search(part)
            if code_match:
                break
    if not code_match:
        code_match = _SHORT_SOP_CODE.search(stem)
    if not code_match:
        code_match = _GENERIC_CODE.search(stem)
    code = _normalise_detected_code(code_match.group(1)) if code_match else None
    version_match = _VERSION.search(stem)
    version = f"V{int(version_match.group(1)):02d}" if version_match else None

    title_source = stem
    if code_match and code_match.string == stem:
        title_source = title_source[: code_match.start()] + " " + title_source[code_match.end() :]
    title_source = _VERSION.sub(" ", title_source)
    title_source = re.sub(r"[._-]+", " ", title_source)
    title_source = re.sub(r"\s+", " ", title_source).strip()
    if not title_source or title_source.upper() == (code or ""):
        parent = path.parent.name
        title_source = re.sub(r"[._-]+", " ", parent).strip() or stem
    title = title_source.title()[:500]
    return InferredMetadata(
        code=code,
        version=version,
        title=title,
        document_type=_document_type(code, path),
        owner_department=_department(path),
    )


def _same_timestamp(value: datetime, timestamp: float) -> bool:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return abs(aware.timestamp() - timestamp) < 0.001


def _safe_files(root: Path, errors: list[str]):
    def onerror(exc: OSError) -> None:
        errors.append(f"{getattr(exc, 'filename', root)}: {exc.strerror or exc}")

    count = 0
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        current = Path(directory)
        allowed_directories: list[str] = []
        for name in names:
            candidate = current / name
            try:
                if candidate.is_symlink():
                    continue
                candidate.resolve().relative_to(root)
                allowed_directories.append(name)
            except (OSError, ValueError):
                errors.append(f"Skipped unsafe folder: {candidate}")
        names[:] = allowed_directories
        for filename in filenames:
            # Microsoft Office creates incomplete lock files beside open documents.
            # They are not controlled sources and cannot be previewed or registered.
            if filename.startswith("~$"):
                continue
            count += 1
            if count > MAX_INVENTORY_FILES:
                raise RuntimeError(f"Controlled source exceeds the safety limit of {MAX_INVENTORY_FILES:,} files")
            candidate = current / filename
            try:
                if candidate.is_symlink():
                    continue
                resolved = candidate.resolve()
                resolved.relative_to(root)
                if resolved.is_file():
                    yield resolved
            except (OSError, ValueError) as exc:
                errors.append(f"Skipped unreadable file {candidate}: {exc}")


def run_source_scan(db: Session, *, trigger: str, requested_by: int | None) -> SourceScanRun:
    if not _scan_lock.acquire(blocking=False):
        raise RuntimeError("A controlled-source scan is already running")
    scan = SourceScanRun(trigger=trigger, status="RUNNING", requested_by=requested_by)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    try:
        root = source_root()
        if not root.exists() or not root.is_dir():
            raise RuntimeError("The configured controlled-document folder is unavailable")

        existing = {item.relative_path: item for item in db.scalars(select(SourceInventoryFile)).all()}
        seen: set[str] = set()
        errors: list[str] = []
        now = datetime.now(timezone.utc)
        hashed = 0
        reused_hash = 0
        supported = 0
        unsupported = 0
        digest = hashlib.sha256()

        for path in _safe_files(root, errors):
            relative_path = path.relative_to(root).as_posix()
            seen.add(relative_path)
            stat = path.stat()
            extension = path.suffix.lower()
            is_supported = extension in ALLOWED_EXTENSIONS
            metadata = infer_metadata(relative_path)
            previous = existing.get(relative_path)
            source_hash: str | None = None
            scan_error: str | None = None
            if is_supported:
                supported += 1
                if (
                    previous
                    and previous.source_sha256
                    and previous.source_size == stat.st_size
                    and _same_timestamp(previous.source_modified_at, stat.st_mtime)
                    and not previous.scan_error
                ):
                    source_hash = previous.source_sha256
                    reused_hash += 1
                else:
                    try:
                        source_hash = sha256_file(path)
                        hashed += 1
                    except OSError as exc:
                        scan_error = str(exc)
                        errors.append(f"Unable to hash {relative_path}: {exc}")
            else:
                unsupported += 1

            item = previous or SourceInventoryFile(
                relative_path=relative_path,
                extension=extension or "[none]",
                is_supported=is_supported,
                source_size=stat.st_size,
                source_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                last_scan_id=scan.id,
            )
            item.extension = extension or "[none]"
            item.is_supported = is_supported
            item.source_size = stat.st_size
            item.source_modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            item.source_sha256 = source_hash
            item.inferred_code = metadata.code
            item.inferred_version = metadata.version
            item.inferred_title = metadata.title
            item.inferred_document_type = metadata.document_type
            item.inferred_owner_department = metadata.owner_department
            item.last_seen_at = now
            item.missing_since = None
            item.last_scan_id = scan.id
            item.scan_error = scan_error
            if previous is None:
                db.add(item)
            digest.update(f"{relative_path}|{stat.st_size}|{stat.st_mtime_ns}|{source_hash or ''}\n".encode())

        missing = 0
        for relative_path, item in existing.items():
            if relative_path not in seen:
                missing += 1
                item.missing_since = item.missing_since or now

        counts = {
            "files_seen": len(seen),
            "supported": supported,
            "unsupported": unsupported,
            "missing": missing,
            "errors": len(errors),
            "hashed": hashed,
            "hashes_reused": reused_hash,
            "inventory_sha256": digest.hexdigest(),
            "sample_errors": errors[:20],
        }
        scan.status = "COMPLETE_WITH_WARNINGS" if errors else "COMPLETE"
        scan.completed_at = now
        scan.counts_json = counts
        db.commit()
        db.refresh(scan)
        return scan
    except Exception as exc:
        db.rollback()
        failed_scan = db.get(SourceScanRun, scan.id)
        if failed_scan:
            failed_scan.status = "FAILED"
            failed_scan.completed_at = datetime.now(timezone.utc)
            failed_scan.error_message = str(exc)[:5000]
            db.commit()
        raise
    finally:
        _scan_lock.release()


def inventory_snapshot(db: Session) -> dict:
    latest = db.scalar(select(SourceScanRun).order_by(SourceScanRun.started_at.desc()).limit(1))
    inventory = db.scalars(select(SourceInventoryFile).order_by(SourceInventoryFile.relative_path)).all()
    versions = db.execute(
        select(DocumentVersion, DocumentFamily).join(DocumentFamily, DocumentFamily.id == DocumentVersion.family_id)
    ).all()
    versions_by_path: dict[str, list[tuple[DocumentVersion, DocumentFamily]]] = defaultdict(list)
    versions_by_hash: dict[str, list[tuple[DocumentVersion, DocumentFamily]]] = defaultdict(list)
    versions_by_key: dict[tuple[str, str], list[tuple[DocumentVersion, DocumentFamily]]] = defaultdict(list)
    for version, family in versions:
        versions_by_path[version.relative_path].append((version, family))
        versions_by_hash[version.source_sha256].append((version, family))
        versions_by_key[(family.code.upper(), version.version_label.upper())].append((version, family))

    current_supported = [item for item in inventory if item.is_supported and item.missing_since is None]
    hash_counts = Counter(item.source_sha256 for item in current_supported if item.source_sha256)
    inferred_counts = Counter(
        (item.inferred_code.upper(), item.inferred_version.upper())
        for item in current_supported
        if item.inferred_code and item.inferred_version
    )

    items: list[dict] = []
    counts: Counter[str] = Counter()
    priority = {
        "CHANGED": 0,
        "MISSING": 1,
        "SCAN_ERROR": 2,
        "UNREGISTERED": 3,
        "DUPLICATE": 4,
        "UNSUPPORTED": 5,
        "REGISTERED": 6,
    }
    for item in inventory:
        registered: tuple[DocumentVersion, DocumentFamily] | None = None
        classification = "UNREGISTERED"
        duplicate_reasons: list[str] = []
        if item.missing_since is not None:
            classification = "MISSING"
        elif item.scan_error:
            classification = "SCAN_ERROR"
        elif not item.is_supported:
            classification = "UNSUPPORTED"
        else:
            exact = versions_by_path.get(item.relative_path, [])
            registered = next(
                ((version, family) for version, family in exact if version.source_sha256 == item.source_sha256),
                None,
            )
            if registered:
                classification = "REGISTERED"
            elif exact:
                classification = "CHANGED"
                registered = exact[0]
            else:
                same_hash = versions_by_hash.get(item.source_sha256 or "", [])
                inferred_key = (
                    (item.inferred_code.upper(), item.inferred_version.upper())
                    if item.inferred_code and item.inferred_version
                    else None
                )
                if same_hash:
                    duplicate_reasons.append("The same file content is already registered at another path")
                    registered = same_hash[0]
                if item.source_sha256 and hash_counts[item.source_sha256] > 1:
                    duplicate_reasons.append("Identical file content exists at more than one source path")
                if inferred_key and inferred_counts[inferred_key] > 1:
                    duplicate_reasons.append("More than one source file has the same inferred document and version")
                if inferred_key and inferred_key in versions_by_key:
                    duplicate_reasons.append("The inferred document and version are already registered")
                    registered = versions_by_key[inferred_key][0]
                if duplicate_reasons:
                    classification = "DUPLICATE"

        counts[classification] += 1
        version, family = registered if registered else (None, None)
        items.append(
            {
                "id": item.id,
                "relative_path": item.relative_path,
                "extension": item.extension,
                "is_supported": item.is_supported,
                "source_size": item.source_size,
                "source_modified_at": item.source_modified_at,
                "source_sha256": item.source_sha256,
                "classification": classification,
                "duplicate_reasons": duplicate_reasons,
                "scan_error": item.scan_error,
                "missing_since": item.missing_since,
                "inferred": {
                    "code": item.inferred_code or "",
                    "version_label": item.inferred_version or "",
                    "title": item.inferred_title or "",
                    "document_type": item.inferred_document_type or "MISC",
                    "owner_department": item.inferred_owner_department or "",
                    "issue_date": item.source_modified_at.date().isoformat(),
                },
                "ready_for_import": classification == "UNREGISTERED"
                and bool(item.inferred_code and item.inferred_version and item.inferred_title),
                "registered_document": (
                    {
                        "family_id": family.id,
                        "code": family.code,
                        "title": family.title,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "status": version.status,
                    }
                    if version and family
                    else None
                ),
            }
        )
    items.sort(key=lambda row: (priority.get(row["classification"], 99), row["relative_path"].lower()))
    return {
        "latest_scan": (
            {
                "id": latest.id,
                "trigger": latest.trigger,
                "status": latest.status,
                "started_at": latest.started_at,
                "completed_at": latest.completed_at,
                "counts": latest.counts_json or {},
                "error_message": latest.error_message,
            }
            if latest
            else None
        ),
        "counts": {name: counts.get(name, 0) for name in priority},
        "items": items,
    }
