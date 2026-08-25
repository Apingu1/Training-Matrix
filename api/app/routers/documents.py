from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..audit import model_snapshot, record_audit
from ..database import get_db
from ..models import (
    ControlledCopyIssue,
    DocumentFamily,
    DocumentVersion,
    RoleDocumentRequirement,
    SourceInventoryFile,
    VersionSignature,
)
from ..schemas import (
    BaselineImportRequest,
    ControlledCopyClose,
    ControlledCopyCreate,
    DocumentCreate,
    DocumentTransition,
    DocumentUpdate,
    DocumentVersionCreate,
    SourceScanRequest,
)
from ..security import (
    AuthContext,
    as_utc,
    client_ip,
    require_any_permission,
    require_permission,
    verify_password,
)
from ..services.file_source import (
    browse_source,
    inspect_source,
    rendered_pdf,
    resolve_source,
    source_status,
)
from ..services.source_discovery import inventory_snapshot, run_source_scan
from ..services.training import (
    assign_released_version,
    cancel_incomplete_for_superseded_version,
)

router = APIRouter(tags=["Controlled Documents"])
DOCUMENT_TYPES = {
    "SOP",
    "FORM",
    "COM",
    "LOG_BOOK",
    "QF",
    "ED",
    "AWARENESS_BRIEF",
    "MISC",
}
MANAGE_PERMISSIONS = {"documents.manage", "documents.review", "documents.approve"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def version_dict(version: DocumentVersion, *, include_path: bool = False) -> dict:
    payload = {
        "id": version.id,
        "family_id": version.family_id,
        "version_label": version.version_label,
        "status": version.status,
        "source_sha256": version.source_sha256,
        "source_size": version.source_size,
        "source_modified_at": version.source_modified_at,
        "change_summary": version.change_summary,
        "training_impact": version.training_impact,
        "training_impact_reason": version.training_impact_reason,
        "issue_date": version.issue_date,
        "approved_at": version.approved_at,
        "effective_at": version.effective_at,
        "review_due_date": version.review_due_date,
        "superseded_at": version.superseded_at,
        "created_by": version.created_by,
        "approved_by": version.approved_by,
        "released_by": version.released_by,
        "created_at": version.created_at,
    }
    if include_path:
        payload["relative_path"] = version.relative_path
    return payload


def controlled_copy_dict(copy: ControlledCopyIssue) -> dict:
    return model_snapshot(copy)


def family_dict(
    family: DocumentFamily,
    *,
    include_versions: bool = False,
    include_path: bool = False,
) -> dict:
    released = next((version for version in family.versions if version.status == "RELEASED"), None)
    forthcoming = next(
        (version for version in family.versions if version.status == "ISSUED_NOT_EFFECTIVE"),
        None,
    )
    result = {
        "id": family.id,
        "code": family.code,
        "title": family.title,
        "document_type": family.document_type,
        "owner_department": family.owner_department,
        "description": family.description,
        "review_interval_months": family.review_interval_months,
        "is_active": family.is_active,
        "created_at": family.created_at,
        "current_version": version_dict(released, include_path=include_path) if released else None,
        "forthcoming_version": version_dict(forthcoming, include_path=include_path) if forthcoming else None,
    }
    if include_versions:
        result["versions"] = [version_dict(version, include_path=include_path) for version in family.versions]
    return result


def ensure_file_unchanged(version: DocumentVersion) -> None:
    metadata = inspect_source(version.relative_path)
    if metadata.sha256 != version.source_sha256:
        raise HTTPException(
            status_code=409,
            detail="The shared-folder file has changed since this controlled version was registered",
        )


def sign_version(
    db: Session,
    version: DocumentVersion,
    auth: AuthContext,
    request: Request,
    *,
    meaning: str,
    statement: str,
) -> None:
    db.add(
        VersionSignature(
            document_version_id=version.id,
            user_id=auth.user.id,
            meaning=meaning,
            statement=statement,
            source_sha256=version.source_sha256,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500],
        )
    )


def activate_version(
    db: Session,
    version: DocumentVersion,
    *,
    actor_user_id: int | None,
    reason: str,
) -> dict:
    ensure_file_unchanged(version)
    previous = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.family_id == version.family_id,
            DocumentVersion.status == "RELEASED",
            DocumentVersion.id != version.id,
        )
    ).all()
    cancelled = 0
    copies_to_recall = 0
    now = utcnow()
    for old_version in previous:
        old_version.status = "SUPERSEDED"
        old_version.superseded_at = now
        cancelled += cancel_incomplete_for_superseded_version(
            db,
            old_version.id,
            reason=f"Superseded by version {version.version_label}",
        )
        copies_to_recall += db.scalar(
            select(func.count(ControlledCopyIssue.id)).where(
                ControlledCopyIssue.document_version_id == old_version.id,
                ControlledCopyIssue.status == "ISSUED",
            )
        )
    version.status = "RELEASED"
    version.effective_at = version.effective_at or now
    version.issue_date = version.issue_date or date.today()
    created = assign_released_version(db, version, assigned_by=actor_user_id)
    return {
        "previous_versions_superseded": len(previous),
        "old_assignments_cancelled": cancelled,
        "assignments_created": created,
        "superseded_controlled_copies_to_recall": copies_to_recall,
    }


def activate_due_versions(db: Session) -> list[dict]:
    due = db.scalars(
        select(DocumentVersion).where(
            DocumentVersion.status == "ISSUED_NOT_EFFECTIVE",
            DocumentVersion.effective_at.is_not(None),
            DocumentVersion.effective_at <= utcnow(),
        )
    ).all()
    results = []
    for version in due:
        try:
            details = activate_version(
                db,
                version,
                actor_user_id=version.released_by,
                reason="Scheduled effective date reached",
            )
            record_audit(
                db,
                event_type="DOCUMENT_VERSION_EFFECTIVE",
                actor_username="SYSTEM",
                entity_type="DOCUMENT_VERSION",
                entity_id=version.id,
                reason="Scheduled effective date reached",
                after=version_dict(version, include_path=True),
                metadata=details,
            )
            results.append({"version_id": version.id, "success": True, **details})
        except HTTPException as exc:
            record_audit(
                db,
                event_type="DOCUMENT_ACTIVATION_FAILED",
                actor_username="SYSTEM",
                entity_type="DOCUMENT_VERSION",
                entity_id=version.id,
                success=False,
                reason=str(exc.detail),
            )
            results.append({"version_id": version.id, "success": False, "error": str(exc.detail)})
    if due:
        db.commit()
    return results


@router.get("/documents/source/status")
def get_source_status(
    _: AuthContext = Depends(require_permission("settings.manage")),
):
    return source_status()


@router.get("/documents/source/browse")
def browse_document_source(
    path: str = Query(default=""),
    _: AuthContext = Depends(require_permission("documents.manage")),
):
    return browse_source(path)


@router.get("/documents/source/inventory")
def get_source_inventory(
    _: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    return inventory_snapshot(db)


@router.post("/documents/source/scan")
def scan_document_source(
    payload: SourceScanRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    try:
        scan = run_source_scan(db, trigger="MANUAL", requested_by=auth.user.id)
    except Exception as exc:
        record_audit(
            db,
            event_type="CONTROLLED_SOURCE_SCAN_FAILED",
            request=request,
            actor=auth,
            entity_type="SOURCE_SCAN",
            success=False,
            reason=payload.reason,
            metadata={"error": str(exc)},
        )
        db.commit()
        status_code = 409 if isinstance(exc, RuntimeError) and "already running" in str(exc).lower() else 503
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    record_audit(
        db,
        event_type="CONTROLLED_SOURCE_SCAN_COMPLETED",
        request=request,
        actor=auth,
        entity_type="SOURCE_SCAN",
        entity_id=scan.id,
        reason=payload.reason,
        after={"status": scan.status, "counts": scan.counts_json},
    )
    db.commit()
    return inventory_snapshot(db)


@router.post("/documents/source/baseline-import", status_code=201)
def import_approved_baseline(
    payload: BaselineImportRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.approve")),
    db: Session = Depends(get_db),
):
    if "documents.manage" not in auth.permissions:
        raise HTTPException(status_code=403, detail="Baseline import also requires document-management permission")
    if payload.confirmation != "IMPORT APPROVED DOCUMENT BASELINE":
        raise HTTPException(status_code=400, detail="Enter exactly: IMPORT APPROVED DOCUMENT BASELINE")
    if not verify_password(payload.password, auth.user.password_hash):
        raise HTTPException(status_code=401, detail="Password re-authentication failed")

    input_paths: set[str] = set()
    input_codes: set[str] = set()
    input_hashes: set[str] = set()
    prepared: list[tuple] = []
    for item in payload.items:
        code = item.code.strip().upper()
        version_label = item.version_label.strip().upper()
        document_type = item.document_type.strip().upper().replace(" ", "_")
        if document_type not in DOCUMENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported document type for {item.relative_path}")
        if item.relative_path in input_paths:
            raise HTTPException(status_code=409, detail=f"Source path selected more than once: {item.relative_path}")
        if code in input_codes:
            raise HTTPException(
                status_code=409,
                detail=f"Select only one approved current version for document {code}",
            )
        expected_hash = item.expected_sha256.lower()
        inventoried = db.scalar(
            select(SourceInventoryFile).where(SourceInventoryFile.relative_path == item.relative_path)
        )
        if (
            inventoried is None
            or not inventoried.is_supported
            or inventoried.missing_since is not None
            or inventoried.scan_error
            or inventoried.source_sha256 != expected_hash
        ):
            raise HTTPException(
                status_code=409,
                detail=f"{item.relative_path} is not an unchanged supported file from the latest source inventory; rescan before importing",
            )
        if expected_hash in input_hashes:
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate file content selected for baseline import: {item.relative_path}",
            )
        source = inspect_source(item.relative_path)
        if source.sha256 != expected_hash:
            raise HTTPException(
                status_code=409,
                detail=f"{item.relative_path} changed after the discovery scan; rescan before importing",
            )
        if db.scalar(select(DocumentVersion.id).where(DocumentVersion.relative_path == source.relative_path).limit(1)):
            raise HTTPException(status_code=409, detail=f"Source path is already registered: {source.relative_path}")
        family = db.scalar(
            select(DocumentFamily).options(selectinload(DocumentFamily.versions)).where(DocumentFamily.code == code)
        )
        if family and family.versions:
            raise HTTPException(
                status_code=409,
                detail=f"{code} already has controlled history; use the normal revision workflow",
            )
        input_paths.add(source.relative_path)
        input_codes.add(code)
        input_hashes.add(expected_hash)
        prepared.append((item, source, family, code, version_label, document_type))

    batch_id = str(uuid.uuid4())
    imported: list[dict] = []
    assignments_created = 0
    effective_now = utcnow()
    batch_digest = hashlib.sha256()
    try:
        for item, source, family, code, version_label, document_type in prepared:
            if family is None:
                family = DocumentFamily(
                    code=code,
                    title=item.title.strip(),
                    document_type=document_type,
                    owner_department=item.owner_department.strip(),
                    description="Initial approved baseline imported from the external controlled-document source.",
                    review_interval_months=item.review_interval_months,
                    created_by=auth.user.id,
                )
                db.add(family)
                db.flush()
            else:
                family.title = item.title.strip()
                family.document_type = document_type
                family.owner_department = item.owner_department.strip()
                family.review_interval_months = item.review_interval_months

            version = DocumentVersion(
                family_id=family.id,
                version_label=version_label,
                status="RELEASED",
                relative_path=source.relative_path,
                source_sha256=source.sha256,
                source_size=source.size,
                source_modified_at=source.modified_at,
                change_summary="Initial approved controlled-document baseline import",
                training_impact="RETRAIN",
                issue_date=item.issue_date or source.modified_at.date(),
                approved_at=effective_now,
                effective_at=effective_now,
                review_due_date=item.review_due_date,
                created_by=auth.user.id,
                approved_by=auth.user.id,
                released_by=auth.user.id,
            )
            db.add(version)
            db.flush()
            db.add(
                VersionSignature(
                    document_version_id=version.id,
                    user_id=auth.user.id,
                    meaning="BASELINE_IMPORT_RELEASE",
                    statement=(
                        "I confirm this file was already approved in Eaststone's external controlled-document "
                        "system and authorise its initial baseline registration and release."
                    ),
                    source_sha256=source.sha256,
                    ip_address=client_ip(request),
                    user_agent=request.headers.get("user-agent", "")[:500],
                )
            )
            assignments_created += assign_released_version(db, version, assigned_by=auth.user.id)
            after = {
                "family": family_dict(family),
                "version": version_dict(version, include_path=True),
                "baseline_import_batch_id": batch_id,
            }
            record_audit(
                db,
                event_type="DOCUMENT_BASELINE_IMPORTED",
                request=request,
                actor=auth,
                entity_type="DOCUMENT_VERSION",
                entity_id=version.id,
                reason=payload.reason,
                after=after,
                metadata={
                    "baseline_import_batch_id": batch_id,
                    "source_sha256": source.sha256,
                    "electronic_signature_meaning": "BASELINE_IMPORT_RELEASE",
                },
            )
            imported.append(
                {
                    "family_id": family.id,
                    "version_id": version.id,
                    "code": family.code,
                    "version_label": version.version_label,
                    "relative_path": source.relative_path,
                    "source_sha256": source.sha256,
                }
            )
            batch_digest.update(
                f"{family.code}|{version.version_label}|{source.relative_path}|{source.sha256}\n".encode()
            )
        record_audit(
            db,
            event_type="DOCUMENT_BASELINE_IMPORT_COMPLETED",
            request=request,
            actor=auth,
            entity_type="BASELINE_IMPORT",
            entity_id=batch_id,
            reason=payload.reason,
            after={
                "documents_imported": len(imported),
                "assignments_created": assignments_created,
                "batch_sha256": batch_digest.hexdigest(),
            },
            metadata={"version_ids": [item["version_id"] for item in imported]},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The baseline conflicts with an existing document code, version or released record",
        ) from exc
    return {
        "batch_id": batch_id,
        "documents_imported": len(imported),
        "assignments_created": assignments_created,
        "batch_sha256": batch_digest.hexdigest(),
        "items": imported,
    }


@router.get("/documents")
def list_documents(
    search: str | None = Query(default=None, max_length=200),
    document_type: str | None = None,
    owner_department: str | None = None,
    include_inactive: bool = False,
    auth: AuthContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
):
    query = select(DocumentFamily).options(selectinload(DocumentFamily.versions))
    if not include_inactive or not auth.permissions.intersection(MANAGE_PERMISSIONS):
        query = query.where(DocumentFamily.is_active.is_(True))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(DocumentFamily.code.ilike(pattern), DocumentFamily.title.ilike(pattern)))
    if document_type:
        query = query.where(DocumentFamily.document_type == document_type.upper())
    if owner_department:
        query = query.where(DocumentFamily.owner_department == owner_department)
    families = db.scalars(query.order_by(DocumentFamily.code)).unique().all()
    can_manage = bool(auth.permissions.intersection(MANAGE_PERMISSIONS))
    return [family_dict(family, include_versions=False, include_path=can_manage) for family in families]


@router.get("/documents/{family_id}")
def get_document(
    family_id: int,
    auth: AuthContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
):
    family = db.scalar(
        select(DocumentFamily).options(selectinload(DocumentFamily.versions)).where(DocumentFamily.id == family_id)
    )
    if not family:
        raise HTTPException(status_code=404, detail="Controlled document not found")
    can_manage = bool(auth.permissions.intersection(MANAGE_PERMISSIONS))
    return family_dict(family, include_versions=can_manage, include_path=can_manage)


@router.post("/documents", status_code=201)
def create_document(
    payload: DocumentCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    document_type = payload.document_type.strip().upper().replace(" ", "_")
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Document type must be one of: {', '.join(sorted(DOCUMENT_TYPES))}",
        )
    family = DocumentFamily(
        code=payload.code.strip().upper(),
        title=payload.title.strip(),
        document_type=document_type,
        owner_department=payload.owner_department.strip(),
        description=payload.description,
        review_interval_months=payload.review_interval_months,
        created_by=auth.user.id,
    )
    db.add(family)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Document code already exists") from exc
    record_audit(
        db,
        event_type="DOCUMENT_CREATED",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_FAMILY",
        entity_id=family.id,
        reason=payload.reason,
        after=model_snapshot(family),
    )
    db.commit()
    db.refresh(family)
    return family_dict(family)


@router.patch("/documents/{family_id}")
def update_document(
    family_id: int,
    payload: DocumentUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    family = db.get(DocumentFamily, family_id)
    if not family:
        raise HTTPException(status_code=404, detail="Controlled document not found")
    if payload.is_active is False:
        current_version = db.scalar(
            select(DocumentVersion.id)
            .where(
                DocumentVersion.family_id == family.id,
                DocumentVersion.status.in_({"RELEASED", "ISSUED_NOT_EFFECTIVE"}),
            )
            .limit(1)
        )
        active_requirement = db.scalar(
            select(RoleDocumentRequirement.id)
            .where(
                RoleDocumentRequirement.document_family_id == family.id,
                RoleDocumentRequirement.is_active.is_(True),
            )
            .limit(1)
        )
        if current_version or active_requirement:
            raise HTTPException(
                status_code=409,
                detail="Obsolete the effective version and retire active role requirements before deactivating this document",
            )
    before = model_snapshot(family)
    for field in (
        "title",
        "owner_department",
        "description",
        "review_interval_months",
        "is_active",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(family, field, value)
    if payload.document_type is not None:
        document_type = payload.document_type.strip().upper().replace(" ", "_")
        if document_type not in DOCUMENT_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported document type")
        family.document_type = document_type
    record_audit(
        db,
        event_type="DOCUMENT_UPDATED",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_FAMILY",
        entity_id=family.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(family),
    )
    db.commit()
    return {"ok": True}


@router.post("/documents/{family_id}/versions", status_code=201)
def create_document_version(
    family_id: int,
    payload: DocumentVersionCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    family = db.get(DocumentFamily, family_id)
    if not family or not family.is_active:
        raise HTTPException(status_code=404, detail="Active controlled document not found")
    if payload.training_impact == "NO_RETRAIN" and not (payload.training_impact_reason or "").strip():
        raise HTTPException(
            status_code=400,
            detail="An approved rationale is required when retraining is not required",
        )
    source = inspect_source(payload.relative_path)
    version = DocumentVersion(
        family_id=family.id,
        version_label=payload.version_label.strip().upper(),
        status="DRAFT",
        relative_path=source.relative_path,
        source_sha256=source.sha256,
        source_size=source.size,
        source_modified_at=source.modified_at,
        change_summary=payload.change_summary,
        training_impact=payload.training_impact,
        training_impact_reason=payload.training_impact_reason,
        issue_date=payload.issue_date,
        effective_at=payload.effective_at,
        review_due_date=payload.review_due_date,
        created_by=auth.user.id,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This version already exists for the document") from exc
    record_audit(
        db,
        event_type="DOCUMENT_VERSION_CREATED",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_VERSION",
        entity_id=version.id,
        reason=payload.reason,
        after=version_dict(version, include_path=True),
    )
    db.commit()
    return version_dict(version, include_path=True)


@router.post("/document-versions/{version_id}/transition")
def transition_document_version(
    version_id: int,
    payload: DocumentTransition,
    request: Request,
    auth: AuthContext = Depends(require_any_permission("documents.manage", "documents.review", "documents.approve")),
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
    before = version_dict(version, include_path=True)
    action = payload.action
    metadata: dict = {}

    def verify_transition_source() -> None:
        try:
            ensure_file_unchanged(version)
        except HTTPException as exc:
            record_audit(
                db,
                event_type="DOCUMENT_INTEGRITY_CHECK_FAILED",
                request=request,
                actor=auth,
                entity_type="DOCUMENT_VERSION",
                entity_id=version.id,
                success=False,
                reason=str(exc.detail),
                metadata={"attempted_action": action},
            )
            db.commit()
            raise

    if action == "REFRESH_SOURCE":
        if "documents.manage" not in auth.permissions or version.status != "DRAFT":
            raise HTTPException(
                status_code=409,
                detail="Only Document Control can refresh the file fingerprint of a draft",
            )
        source = inspect_source(version.relative_path)
        version.source_sha256 = source.sha256
        version.source_size = source.size
        version.source_modified_at = source.modified_at
        metadata = {"refreshed_source_sha256": source.sha256}
    elif action == "SUBMIT":
        if "documents.review" not in auth.permissions or version.status != "DRAFT":
            raise HTTPException(
                status_code=409,
                detail="Only a draft can be submitted by an authorised reviewer",
            )
        verify_transition_source()
        version.status = "IN_REVIEW"
    elif action == "RETURN_TO_DRAFT":
        if "documents.review" not in auth.permissions or version.status not in {
            "IN_REVIEW",
            "APPROVED",
        }:
            raise HTTPException(status_code=409, detail="This version cannot be returned to draft")
        version.status = "DRAFT"
        version.approved_at = None
        version.approved_by = None
    elif action == "APPROVE":
        if "documents.approve" not in auth.permissions or version.status != "IN_REVIEW":
            raise HTTPException(status_code=409, detail="Only an in-review version can be approved")
        if version.created_by == auth.user.id:
            raise HTTPException(
                status_code=409,
                detail="The revision creator cannot independently approve the same version",
            )
        if not payload.password or not verify_password(payload.password, auth.user.password_hash):
            raise HTTPException(status_code=401, detail="Password re-authentication failed")
        verify_transition_source()
        version.status = "APPROVED"
        version.approved_at = utcnow()
        version.approved_by = auth.user.id
        sign_version(
            db,
            version,
            auth,
            request,
            meaning="DOCUMENT_APPROVAL",
            statement=f"Approved controlled document version {version.version_label}",
        )
    elif action == "RELEASE":
        if "documents.approve" not in auth.permissions or version.status != "APPROVED":
            raise HTTPException(status_code=409, detail="Only an approved version can be released")
        if not payload.password or not verify_password(payload.password, auth.user.password_hash):
            raise HTTPException(status_code=401, detail="Password re-authentication failed")
        verify_transition_source()
        version.released_by = auth.user.id
        version.effective_at = version.effective_at or utcnow()
        sign_version(
            db,
            version,
            auth,
            request,
            meaning="DOCUMENT_RELEASE",
            statement=f"Released controlled document version {version.version_label}",
        )
        if as_utc(version.effective_at) > utcnow():
            version.status = "ISSUED_NOT_EFFECTIVE"
            metadata = {"scheduled_effective_at": version.effective_at.isoformat()}
        else:
            metadata = activate_version(db, version, actor_user_id=auth.user.id, reason=payload.reason)
    elif action == "OBSOLETE":
        if "documents.approve" not in auth.permissions or version.status not in {
            "RELEASED",
            "ISSUED_NOT_EFFECTIVE",
        }:
            raise HTTPException(
                status_code=409,
                detail="Only a released or forthcoming version can be made obsolete",
            )
        if not payload.password or not verify_password(payload.password, auth.user.password_hash):
            raise HTTPException(status_code=401, detail="Password re-authentication failed")
        verify_transition_source()
        sign_version(
            db,
            version,
            auth,
            request,
            meaning="DOCUMENT_OBSOLESCENCE",
            statement=f"Made controlled document version {version.version_label} obsolete",
        )
        version.status = "OBSOLETE"
        version.superseded_at = utcnow()
        metadata = {
            "assignments_cancelled": cancel_incomplete_for_superseded_version(
                db, version.id, reason=f"Document made obsolete: {payload.reason}"
            ),
            "controlled_copies_to_recall": db.scalar(
                select(func.count(ControlledCopyIssue.id)).where(
                    ControlledCopyIssue.document_version_id == version.id,
                    ControlledCopyIssue.status == "ISSUED",
                )
            ),
        }

    record_audit(
        db,
        event_type=f"DOCUMENT_{action}",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_VERSION",
        entity_id=version.id,
        reason=payload.reason,
        before=before,
        after=version_dict(version, include_path=True),
        metadata=metadata,
    )
    db.commit()
    return {"version": version_dict(version, include_path=True), **metadata}


@router.get("/document-versions/{version_id}/controlled-copies")
def list_controlled_copies(
    version_id: int,
    _: AuthContext = Depends(require_any_permission("documents.manage", "documents.approve", "audit.view")),
    db: Session = Depends(get_db),
):
    if not db.get(DocumentVersion, version_id):
        raise HTTPException(status_code=404, detail="Document version not found")
    copies = db.scalars(
        select(ControlledCopyIssue)
        .where(ControlledCopyIssue.document_version_id == version_id)
        .order_by(ControlledCopyIssue.issued_at.desc())
    ).all()
    return [controlled_copy_dict(copy) for copy in copies]


@router.post("/document-versions/{version_id}/controlled-copies", status_code=201)
def issue_controlled_copy(
    version_id: int,
    payload: ControlledCopyCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
    if version.status != "RELEASED":
        raise HTTPException(
            status_code=409,
            detail="Controlled copies can only be issued for the current effective version",
        )
    copy = ControlledCopyIssue(
        document_version_id=version.id,
        copy_number=payload.copy_number.strip(),
        department=payload.department.strip(),
        location=payload.location.strip(),
        issued_to=payload.issued_to.strip() if payload.issued_to else None,
        issued_by=auth.user.id,
    )
    db.add(copy)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="That controlled-copy number already exists for this version",
        ) from exc
    record_audit(
        db,
        event_type="CONTROLLED_COPY_ISSUED",
        request=request,
        actor=auth,
        entity_type="CONTROLLED_COPY",
        entity_id=copy.id,
        reason=payload.reason,
        after=controlled_copy_dict(copy),
        metadata={"source_sha256": version.source_sha256},
    )
    db.commit()
    return controlled_copy_dict(copy)


@router.post("/controlled-copies/{copy_id}/close")
def close_controlled_copy(
    copy_id: int,
    payload: ControlledCopyClose,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.manage")),
    db: Session = Depends(get_db),
):
    copy = db.get(ControlledCopyIssue, copy_id)
    if not copy:
        raise HTTPException(status_code=404, detail="Controlled copy not found")
    if copy.status != "ISSUED":
        raise HTTPException(status_code=409, detail="This controlled copy is already closed")
    before = controlled_copy_dict(copy)
    copy.status = payload.disposition
    copy.closed_at = utcnow()
    copy.closed_by = auth.user.id
    copy.closure_reason = payload.reason
    record_audit(
        db,
        event_type=f"CONTROLLED_COPY_{payload.disposition}",
        request=request,
        actor=auth,
        entity_type="CONTROLLED_COPY",
        entity_id=copy.id,
        reason=payload.reason,
        before=before,
        after=controlled_copy_dict(copy),
    )
    db.commit()
    return controlled_copy_dict(copy)


@router.get("/document-versions/{version_id}/view")
def view_document_version(
    version_id: int,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.view")),
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
    if version.status != "RELEASED" and not auth.permissions.intersection(MANAGE_PERMISSIONS | {"audit.view"}):
        raise HTTPException(
            status_code=403,
            detail="Operators may only view the current effective version",
        )
    try:
        pdf_path, verified_hash = rendered_pdf(version.relative_path, version.source_sha256)
    except HTTPException as exc:
        record_audit(
            db,
            event_type="DOCUMENT_VIEW_BLOCKED",
            request=request,
            actor=auth,
            entity_type="DOCUMENT_VERSION",
            entity_id=version.id,
            success=False,
            reason=str(exc.detail),
            metadata={"relative_path": version.relative_path},
        )
        db.commit()
        raise
    record_audit(
        db,
        event_type="DOCUMENT_VIEWED",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_VERSION",
        entity_id=version.id,
        metadata={"source_sha256": verified_hash, "rendition": "PDF"},
    )
    db.commit()
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{version.family.code if version.family else 'controlled-document'}-{version.version_label}.pdf",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/document-versions/{version_id}/source")
def download_document_source(
    version_id: int,
    request: Request,
    auth: AuthContext = Depends(require_permission("documents.source_download")),
    db: Session = Depends(get_db),
):
    version = db.get(DocumentVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Document version not found")
    try:
        ensure_file_unchanged(version)
    except HTTPException as exc:
        record_audit(
            db,
            event_type="DOCUMENT_SOURCE_DOWNLOAD_BLOCKED",
            request=request,
            actor=auth,
            entity_type="DOCUMENT_VERSION",
            entity_id=version.id,
            success=False,
            reason=str(exc.detail),
        )
        db.commit()
        raise
    path = resolve_source(version.relative_path)
    record_audit(
        db,
        event_type="DOCUMENT_SOURCE_DOWNLOADED",
        request=request,
        actor=auth,
        entity_type="DOCUMENT_VERSION",
        entity_id=version.id,
        metadata={"source_sha256": version.source_sha256},
    )
    db.commit()
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/documents/system/activate-due")
def run_due_activation(
    _: AuthContext = Depends(require_permission("documents.approve")),
    db: Session = Depends(get_db),
):
    return {"results": activate_due_versions(db)}
