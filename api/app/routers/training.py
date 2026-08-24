from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import model_snapshot, record_audit
from ..database import get_db
from ..models import (
    AssignmentSource,
    AuditEvent,
    DocumentFamily,
    DocumentVersion,
    JobRole,
    RoleDocumentRequirement,
    SystemSetting,
    TrainingAcknowledgement,
    TrainingAssignment,
    User,
    UserJobRole,
)
from ..schemas import (
    AcknowledgeRequest,
    AssignmentClosure,
    IndividualAssignmentCreate,
    RequirementCreate,
    RequirementUpdate,
)
from ..security import AuthContext, as_utc, require_permission, utcnow, verify_password
from ..services.file_source import inspect_source
from ..services.training import (
    TRAINING_REQUIREMENT_TYPES,
    active_role_condition,
    assign_requirement,
    displayed_status,
    ensure_assignment,
)

router = APIRouter(prefix="/training", tags=["Training Matrix"])


def configured_due_days(db: Session) -> int:
    setting = db.get(SystemSetting, "training_default_due_days")
    try:
        return max(0, min(3650, int(setting.value))) if setting else 14
    except ValueError:
        return 14


def assignment_dict(assignment: TrainingAssignment, db: Session) -> dict:
    version = db.get(DocumentVersion, assignment.document_version_id)
    family = db.get(DocumentFamily, version.family_id) if version else None
    acknowledgement = db.scalar(
        select(TrainingAcknowledgement).where(TrainingAcknowledgement.assignment_id == assignment.id)
    )
    return {
        "id": assignment.id,
        "user_id": assignment.user_id,
        "document_version_id": assignment.document_version_id,
        "document_family_id": family.id if family else None,
        "document_code": family.code if family else None,
        "document_title": family.title if family else None,
        "document_type": family.document_type if family else None,
        "version_label": version.version_label if version else None,
        "version_status": version.status if version else None,
        "status": displayed_status(assignment),
        "stored_status": assignment.status,
        "requirement_type": assignment.requirement_type,
        "assigned_at": assignment.assigned_at,
        "due_at": assignment.due_at,
        "completed_at": assignment.completed_at,
        "closure_reason": assignment.closure_reason,
        "acknowledgement": {
            "acknowledged_at": acknowledgement.acknowledged_at,
            "statement": acknowledgement.statement,
            "source_sha256": acknowledgement.source_sha256,
            "method": acknowledgement.method,
        }
        if acknowledgement
        else None,
    }


def requirement_dict(requirement: RoleDocumentRequirement) -> dict:
    return {
        "id": requirement.id,
        "job_role_id": requirement.job_role_id,
        "job_role_code": requirement.job_role.code if requirement.job_role else None,
        "job_role_name": requirement.job_role.name if requirement.job_role else None,
        "document_family_id": requirement.document_family_id,
        "document_code": requirement.document_family.code if requirement.document_family else None,
        "document_title": requirement.document_family.title if requirement.document_family else None,
        "requirement_type": requirement.requirement_type,
        "due_days": requirement.due_days,
        "is_active": requirement.is_active,
        "reason": requirement.reason,
        "created_at": requirement.created_at,
    }


@router.get("/configuration")
def training_configuration(
    _: AuthContext = Depends(require_permission("training.manage")),
    db: Session = Depends(get_db),
):
    return {"default_due_days": configured_due_days(db)}


@router.get("/acknowledgement-statement")
def acknowledgement_statement(
    _: AuthContext = Depends(require_permission("training.acknowledge")),
    db: Session = Depends(get_db),
):
    setting = db.get(SystemSetting, "acknowledgement_statement")
    return {
        "statement": setting.value
        if setting
        else "I confirm that I have read and understood this document and will comply with its requirements."
    }


@router.get("/dashboard")
def dashboard(
    auth: AuthContext = Depends(require_permission("training.view_own")),
    db: Session = Depends(get_db),
):
    assignments = db.scalars(select(TrainingAssignment).where(TrainingAssignment.user_id == auth.user.id)).all()
    statuses = [displayed_status(item) for item in assignments]
    current = [item for item in assignments if item.status == "ASSIGNED"]
    return {
        "assigned": statuses.count("ASSIGNED"),
        "overdue": statuses.count("OVERDUE"),
        "completed": statuses.count("COMPLETED"),
        "due_within_7_days": sum(
            1 for item in current if utcnow() <= as_utc(item.due_at) <= utcnow() + timedelta(days=7)
        ),
        "total": len(assignments),
    }


@router.get("/my-assignments")
def my_assignments(
    status_filter: str | None = Query(default=None, alias="status"),
    auth: AuthContext = Depends(require_permission("training.view_own")),
    db: Session = Depends(get_db),
):
    assignments = db.scalars(
        select(TrainingAssignment)
        .where(TrainingAssignment.user_id == auth.user.id)
        .order_by(
            TrainingAssignment.completed_at.desc().nullslast(),
            TrainingAssignment.due_at,
        )
    ).all()
    results = [assignment_dict(item, db) for item in assignments]
    if status_filter:
        results = [item for item in results if item["status"] == status_filter.upper()]
    return results


@router.post("/assignments/{assignment_id}/acknowledge")
def acknowledge_assignment(
    assignment_id: int,
    payload: AcknowledgeRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.acknowledge")),
    db: Session = Depends(get_db),
):
    assignment = db.get(TrainingAssignment, assignment_id)
    if not assignment or assignment.user_id != auth.user.id:
        raise HTTPException(status_code=404, detail="Training assignment not found")
    if assignment.status != "ASSIGNED":
        raise HTTPException(
            status_code=409,
            detail="This assignment is no longer awaiting acknowledgement",
        )
    version = db.get(DocumentVersion, assignment.document_version_id)
    if not version or version.status != "RELEASED":
        raise HTTPException(
            status_code=409,
            detail="Only an effective controlled version can be acknowledged",
        )
    viewed = db.scalar(
        select(AuditEvent.id)
        .where(
            AuditEvent.event_type == "DOCUMENT_VIEWED",
            AuditEvent.actor_user_id == auth.user.id,
            AuditEvent.entity_type == "DOCUMENT_VERSION",
            AuditEvent.entity_id == str(version.id),
            AuditEvent.created_at >= assignment.assigned_at,
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    if not viewed:
        raise HTTPException(
            status_code=409,
            detail="Open the controlled document before acknowledging it",
        )
    if not verify_password(payload.password, auth.user.password_hash):
        raise HTTPException(status_code=401, detail="Password re-authentication failed")
    source = inspect_source(version.relative_path)
    if source.sha256 != version.source_sha256:
        record_audit(
            db,
            event_type="TRAINING_ACKNOWLEDGEMENT_BLOCKED",
            request=request,
            actor=auth,
            entity_type="TRAINING_ASSIGNMENT",
            entity_id=assignment.id,
            success=False,
            reason="Shared-folder file hash no longer matches the registered controlled version",
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="The source file changed outside document control; acknowledgement is blocked",
        )
    setting = db.get(SystemSetting, "acknowledgement_statement")
    statement = setting.value if setting else payload.statement
    acknowledgement = TrainingAcknowledgement(
        assignment_id=assignment.id,
        user_id=auth.user.id,
        document_version_id=version.id,
        statement=statement,
        source_sha256=version.source_sha256,
        method="PASSWORD_REAUTH",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent", "")[:500],
        session_id=auth.session.id,
    )
    db.add(acknowledgement)
    assignment.status = "COMPLETED"
    assignment.completed_at = utcnow()
    record_audit(
        db,
        event_type="TRAINING_ACKNOWLEDGED",
        request=request,
        actor=auth,
        entity_type="TRAINING_ASSIGNMENT",
        entity_id=assignment.id,
        after={
            "document_version_id": version.id,
            "document_code": version.family.code if version.family else None,
            "version_label": version.version_label,
            "source_sha256": version.source_sha256,
            "statement": statement,
            "completed_at": assignment.completed_at,
        },
    )
    db.commit()
    return assignment_dict(assignment, db)


@router.get("/requirements")
def list_requirements(
    job_role_id: int | None = None,
    include_inactive: bool = False,
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    query = select(RoleDocumentRequirement)
    if job_role_id is not None:
        query = query.where(RoleDocumentRequirement.job_role_id == job_role_id)
    if not include_inactive:
        query = query.where(RoleDocumentRequirement.is_active.is_(True))
    requirements = db.scalars(
        query.order_by(
            RoleDocumentRequirement.job_role_id,
            RoleDocumentRequirement.document_family_id,
        )
    ).all()
    return [requirement_dict(item) for item in requirements]


@router.post("/requirements", status_code=201)
def create_requirement(
    payload: RequirementCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.manage")),
    db: Session = Depends(get_db),
):
    role = db.get(JobRole, payload.job_role_id)
    family = db.get(DocumentFamily, payload.document_family_id)
    if not role or not role.is_active or not family or not family.is_active:
        raise HTTPException(status_code=400, detail="Select an active job role and controlled document")
    requirement = RoleDocumentRequirement(
        job_role_id=role.id,
        document_family_id=family.id,
        requirement_type=payload.requirement_type,
        due_days=payload.due_days if payload.due_days is not None else configured_due_days(db),
        is_active=True,
        reason=payload.reason,
        created_by=auth.user.id,
    )
    db.add(requirement)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This document is already mapped to the selected job role",
        ) from exc
    created = assign_requirement(db, requirement, assigned_by=auth.user.id)
    record_audit(
        db,
        event_type="TRAINING_REQUIREMENT_CREATED",
        request=request,
        actor=auth,
        entity_type="ROLE_DOCUMENT_REQUIREMENT",
        entity_id=requirement.id,
        reason=payload.reason,
        after=model_snapshot(requirement),
        metadata={"training_assignments_created": created},
    )
    db.commit()
    return {**requirement_dict(requirement), "training_assignments_created": created}


@router.patch("/requirements/{requirement_id}")
def update_requirement(
    requirement_id: int,
    payload: RequirementUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.manage")),
    db: Session = Depends(get_db),
):
    requirement = db.get(RoleDocumentRequirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Training requirement not found")
    before = model_snapshot(requirement)
    previously_required_training = requirement.is_active and requirement.requirement_type in TRAINING_REQUIREMENT_TYPES
    for field in ("requirement_type", "due_days", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(requirement, field, value)
    requirement.reason = payload.reason
    assignments_created = 0
    assignments_closed = 0
    currently_requires_training = requirement.is_active and requirement.requirement_type in TRAINING_REQUIREMENT_TYPES
    if currently_requires_training:
        assignments_created = assign_requirement(db, requirement, assigned_by=auth.user.id)
        sources = db.scalars(select(AssignmentSource).where(AssignmentSource.requirement_id == requirement.id)).all()
        for source in sources:
            assignment = db.get(TrainingAssignment, source.assignment_id)
            if assignment and assignment.status == "ASSIGNED":
                assignment.requirement_type = requirement.requirement_type
    elif previously_required_training:
        sources = db.scalars(select(AssignmentSource).where(AssignmentSource.requirement_id == requirement.id)).all()
        for source in sources:
            assignment = db.get(TrainingAssignment, source.assignment_id)
            db.delete(source)
            db.flush()
            other_sources = db.scalar(
                select(func.count(AssignmentSource.requirement_id)).where(
                    AssignmentSource.assignment_id == assignment.id
                )
            )
            if assignment and assignment.status == "ASSIGNED" and other_sources == 0 and not assignment.is_individual:
                assignment.status = "CANCELLED"
                assignment.closed_at = utcnow()
                assignment.closure_reason = f"Role requirement no longer requires training: {payload.reason}"
                assignments_closed += 1
    record_audit(
        db,
        event_type="TRAINING_REQUIREMENT_UPDATED",
        request=request,
        actor=auth,
        entity_type="ROLE_DOCUMENT_REQUIREMENT",
        entity_id=requirement.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(requirement),
        metadata={
            "assignments_created": assignments_created,
            "assignments_closed": assignments_closed,
        },
    )
    db.commit()
    return {
        **requirement_dict(requirement),
        "assignments_created": assignments_created,
        "assignments_closed": assignments_closed,
    }


@router.post("/assignments", status_code=201)
def create_individual_assignment(
    payload: IndividualAssignmentCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.manage")),
    db: Session = Depends(get_db),
):
    user = db.get(User, payload.user_id)
    version = db.get(DocumentVersion, payload.document_version_id)
    if not user or not user.is_active or not version or version.status != "RELEASED":
        raise HTTPException(
            status_code=400,
            detail="Select an active user and effective document version",
        )
    assignment, created = ensure_assignment(
        db,
        user_id=user.id,
        version=version,
        requirement=None,
        due_days=payload.due_days if payload.due_days is not None else configured_due_days(db),
        requirement_type=payload.requirement_type,
        assigned_by=auth.user.id,
    )
    record_audit(
        db,
        event_type="INDIVIDUAL_TRAINING_ASSIGNED",
        request=request,
        actor=auth,
        entity_type="TRAINING_ASSIGNMENT",
        entity_id=assignment.id,
        reason=payload.reason,
        after=model_snapshot(assignment),
        metadata={"new_assignment": created},
    )
    db.commit()
    return assignment_dict(assignment, db)


@router.post("/assignments/{assignment_id}/waive")
def waive_assignment(
    assignment_id: int,
    payload: AssignmentClosure,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.waive")),
    db: Session = Depends(get_db),
):
    assignment = db.get(TrainingAssignment, assignment_id)
    if not assignment or assignment.status != "ASSIGNED":
        raise HTTPException(status_code=409, detail="Only an open assignment can be waived")
    before = model_snapshot(assignment)
    assignment.status = "WAIVED"
    assignment.closed_at = utcnow()
    assignment.closure_reason = payload.reason
    record_audit(
        db,
        event_type="TRAINING_ASSIGNMENT_WAIVED",
        request=request,
        actor=auth,
        entity_type="TRAINING_ASSIGNMENT",
        entity_id=assignment.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(assignment),
    )
    db.commit()
    return assignment_dict(assignment, db)


@router.get("/users/{user_id}/assignments")
def user_assignments(
    user_id: int,
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    assignments = db.scalars(
        select(TrainingAssignment).where(TrainingAssignment.user_id == user_id).order_by(TrainingAssignment.due_at)
    ).all()
    return [assignment_dict(item, db) for item in assignments]


@router.get("/matrix/{job_role_id}")
def role_matrix(
    job_role_id: int,
    include_inactive_requirements: bool = False,
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    role = db.get(JobRole, job_role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    requirement_query = select(RoleDocumentRequirement).where(RoleDocumentRequirement.job_role_id == role.id)
    if not include_inactive_requirements:
        requirement_query = requirement_query.where(RoleDocumentRequirement.is_active.is_(True))
    requirements = db.scalars(requirement_query.order_by(RoleDocumentRequirement.document_family_id)).all()
    users = (
        db.scalars(
            select(User)
            .join(UserJobRole, UserJobRole.user_id == User.id)
            .where(
                UserJobRole.job_role_id == role.id,
                active_role_condition(),
                User.is_active.is_(True),
            )
            .order_by(User.display_name)
        )
        .unique()
        .all()
    )
    rows = []
    for requirement in requirements:
        version = db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.family_id == requirement.document_family_id,
                DocumentVersion.status == "RELEASED",
            )
            .order_by(DocumentVersion.effective_at.desc().nullslast())
            .limit(1)
        )
        cells = []
        for user in users:
            assignment = None
            if version:
                assignment = db.scalar(
                    select(TrainingAssignment).where(
                        TrainingAssignment.user_id == user.id,
                        TrainingAssignment.document_version_id == version.id,
                    )
                )
            cells.append(
                {
                    "user_id": user.id,
                    "status": displayed_status(assignment)
                    if assignment
                    else (
                        "REFERENCE"
                        if requirement.requirement_type in {"REFERENCE_ONLY", "CONTROLLED_COPY"}
                        else "NOT_ASSIGNED"
                    ),
                    "due_at": assignment.due_at if assignment else None,
                    "completed_at": assignment.completed_at if assignment else None,
                }
            )
        rows.append(
            {
                "requirement": requirement_dict(requirement),
                "current_version": {
                    "id": version.id,
                    "version_label": version.version_label,
                    "effective_at": version.effective_at,
                }
                if version
                else None,
                "cells": cells,
            }
        )
    return {
        "job_role": {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "department": role.department,
        },
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
            }
            for user in users
        ],
        "rows": rows,
    }


@router.get("/compliance-summary")
def compliance_summary(
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.display_name)).all()
    results = []
    for user in users:
        assignments = db.scalars(
            select(TrainingAssignment)
            .join(
                DocumentVersion,
                DocumentVersion.id == TrainingAssignment.document_version_id,
            )
            .where(
                TrainingAssignment.user_id == user.id,
                DocumentVersion.status == "RELEASED",
            )
        ).all()
        open_items = [item for item in assignments if item.status == "ASSIGNED"]
        completed = [item for item in assignments if item.status == "COMPLETED"]
        overdue = [item for item in open_items if as_utc(item.due_at) < utcnow()]
        denominator = len(open_items) + len(completed)
        results.append(
            {
                "user_id": user.id,
                "display_name": user.display_name,
                "open": len(open_items),
                "overdue": len(overdue),
                "completed": len(completed),
                "compliance_percent": round((len(completed) / denominator * 100), 1) if denominator else 100.0,
            }
        )
    return results
