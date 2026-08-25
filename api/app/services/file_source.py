from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status

from ..config import settings

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_conversion_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    relative_path: str
    sha256: str
    size: int
    modified_at: datetime
    extension: str


def source_root() -> Path:
    return settings.document_root.resolve()


def _is_word_temporary(path: Path) -> bool:
    return path.name.startswith("~$")


def resolve_source(relative_path: str, *, require_file: bool = True) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise HTTPException(status_code=400, detail="A relative document path is required")
    root = source_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Document path escapes the configured source folder") from exc
    if require_file and _is_word_temporary(candidate):
        raise HTTPException(
            status_code=409,
            detail="Microsoft Word temporary lock files (~$...) are not controlled documents. Close the source document and rescan the controlled folder.",
        )
    if require_file and (not candidate.exists() or not candidate.is_file()):
        raise HTTPException(status_code=404, detail="Document source file was not found")
    if require_file and candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX controlled documents are supported",
        )
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_source(relative_path: str) -> SourceMetadata:
    path = resolve_source(relative_path)
    stat = path.stat()
    return SourceMetadata(
        relative_path=path.relative_to(source_root()).as_posix(),
        sha256=sha256_file(path),
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        extension=path.suffix.lower(),
    )


def browse_source(relative_path: str = "") -> dict:
    root = source_root()
    if not root.exists():
        raise HTTPException(
            status_code=503,
            detail="The configured controlled-document folder is unavailable",
        )
    if relative_path:
        current = resolve_source(relative_path, require_file=False)
    else:
        current = root
    if not current.exists() or not current.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    items: list[dict] = []
    try:
        children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="The server cannot read this folder") from exc
    for child in children:
        try:
            resolved = child.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if child.is_dir():
            items.append(
                {
                    "name": child.name,
                    "path": resolved.relative_to(root).as_posix(),
                    "type": "directory",
                }
            )
        elif child.suffix.lower() in ALLOWED_EXTENSIONS and not _is_word_temporary(child):
            stat = child.stat()
            items.append(
                {
                    "name": child.name,
                    "path": resolved.relative_to(root).as_posix(),
                    "type": "file",
                    "extension": child.suffix.lower(),
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    parent = None if current == root else current.parent.relative_to(root).as_posix()
    return {
        "path": current.relative_to(root).as_posix(),
        "parent": parent,
        "items": items,
    }


def source_status() -> dict:
    root = source_root()
    return {
        "configured_path": str(settings.document_root),
        "available": root.exists() and root.is_dir(),
        "readable": os.access(root, os.R_OK) if root.exists() else False,
        "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
    }


def rendered_pdf(relative_path: str, expected_sha256: str) -> tuple[Path, str]:
    source = resolve_source(relative_path)
    current_hash = sha256_file(source)
    if current_hash != expected_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source file has changed outside document control. Access is blocked until a new version is registered.",
        )
    if source.suffix.lower() == ".pdf":
        return source, current_hash

    target = settings.document_cache_root / f"{current_hash}.pdf"
    if target.exists() and target.stat().st_size > 0:
        return target, current_hash

    with _conversion_lock:
        if target.exists() and target.stat().st_size > 0:
            return target, current_hash
        with tempfile.TemporaryDirectory(prefix="training-matrix-docx-") as temp_dir:
            result = subprocess.run(
                [
                    "libreoffice",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nolockcheck",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    temp_dir,
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            converted = Path(temp_dir) / f"{source.stem}.pdf"
            if result.returncode != 0 or not converted.exists():
                diagnostic = (result.stderr or result.stdout or "").strip()
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "DOCX preview conversion failed. The original DOCX remains unchanged and downloadable; "
                        "Document Control should verify that it is a valid Word document."
                        + (f" Converter detail: {diagnostic[:300]}" if diagnostic else "")
                    ),
                )
            temporary_target = settings.document_cache_root / f".{current_hash}.tmp"
            shutil.copyfile(converted, temporary_target)
            os.replace(temporary_target, target)
    return target, current_hash
