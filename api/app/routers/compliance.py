from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..audit import model_snapshot, record_audit
from ..database import get_db
from ..models import (
    AssignmentSource,
    DocumentFamily,
    DocumentVersion,
    JobRole,
    RoleDocumentRequirement,
    SystemSetting,
    TrainingAssignment,
    User,
    UserJobRole,
)
from ..security import AuthContext, require_permission, utcnow
from ..services.training import (
    TRAINING_REQUIREMENT_TYPES,
    active_role_condition,
    assign_requirement,
    displayed_status,
)

router = APIRouter(prefix="/training", tags=["Training Matrix"])


class CurriculumCell(BaseModel):
    job_role_id: int
    document_family_id: int


class CurriculumGridUpdate(BaseModel):
    selected: list[CurriculumCell] = Field(default_factory=list, max_length=10000)
    reason: str = Field(min_length=3, max_length=2000)


def configured_due_days(db: Session) -> int:
    setting = db.get(SystemSetting, "training_default_due_days")
    try:
        return max(0, min(3650, int(setting.value))) if setting else 14
    except (TypeError, ValueError):
        return 14


def configured_compliance_threshold(db: Session) -> float:
    setting = db.get(SystemSetting, "active_compliance_threshold_percent")
    try:
        return max(0.0, min(100.0, float(setting.value))) if setting else 80.0
    except (TypeError, ValueError):
        return 80.0


def current_sop_versions(db: Session) -> list[tuple[DocumentVersion, DocumentFamily]]:
    return db.execute(
        select(DocumentVersion, DocumentFamily)
        .join(DocumentFamily, DocumentFamily.id == DocumentVersion.family_id)
        .where(
            DocumentVersion.status == "RELEASED",
            DocumentFamily.is_active.is_(True),
            DocumentFamily.document_type == "SOP",
        )
        .order_by(DocumentFamily.code)
    ).all()


def active_trainees(db: Session) -> list[User]:
    return (
        db.scalars(
            select(User)
            .join(UserJobRole, UserJobRole.user_id == User.id)
            .join(JobRole, JobRole.id == UserJobRole.job_role_id)
            .where(
                User.is_active.is_(True),
                JobRole.is_active.is_(True),
                active_role_condition(),
            )
            .order_by(User.display_name)
        )
        .unique()
        .all()
    )


def compliance_for_users(db: Session, users: list[User]) -> dict[int, dict]:
    if not users:
        return {}
    current_versions = current_sop_versions(db)
    version_ids = [version.id for version, _ in current_versions]
    user_ids = [user.id for user in users]
    assignments: list[TrainingAssignment] = []
    if version_ids:
        assignments = db.scalars(
            select(TrainingAssignment).where(
                TrainingAssignment.user_id.in_(user_ids),
                TrainingAssignment.document_version_id.in_(version_ids),
                TrainingAssignment.status.in_(("ASSIGNED", "COMPLETED")),
            )
        ).all()

    by_user: dict[int, list[TrainingAssignment]] = defaultdict(list)
    for assignment in assignments:
        by_user[assignment.user_id].append(assignment)

    result: dict[int, dict] = {}
    for user in users:
        required = by_user.get(user.id, [])
        completed = sum(1 for item in required if item.status == "COMPLETED")
        open_items = [item for item in required if item.status == "ASSIGNED"]
        overdue = sum(1 for item in open_items if displayed_status(item) == "OVERDUE")
        total = len(required)
        percent = round((completed / total * 100), 1) if total else 100.0
        result[user.id] = {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "required": total,
            "completed": completed,
            "open": len(open_items),
            "overdue": overdue,
            "compliance_percent": percent,
        }
    return result


def close_requirement_sources(db: Session, requirement: RoleDocumentRequirement, *, reason: str) -> int:
    sources = db.scalars(
        select(AssignmentSource).where(AssignmentSource.requirement_id == requirement.id)
    ).all()
    closed = 0
    for source in sources:
        assignment = db.get(TrainingAssignment, source.assignment_id)
        db.delete(source)
        db.flush()
        remaining = db.scalar(
            select(func.count(AssignmentSource.requirement_id)).where(
                AssignmentSource.assignment_id == source.assignment_id
            )
        )
        if (
            assignment
            and assignment.status == "ASSIGNED"
            and remaining == 0
            and not assignment.is_individual
        ):
            assignment.status = "CANCELLED"
            assignment.closed_at = utcnow()
            assignment.closure_reason = f"Role curriculum requirement removed: {reason}"
            closed += 1
    return closed


@router.get("/compliance-overview")
def compliance_overview(
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    threshold = configured_compliance_threshold(db)
    users = active_trainees(db)
    compliance = compliance_for_users(db, users)
    rows = list(compliance.values())
    below = [item for item in rows if item["compliance_percent"] < threshold]
    average = round(sum(item["compliance_percent"] for item in rows) / len(rows), 1) if rows else 100.0
    return {
        "threshold_percent": threshold,
        "operator_count": len(rows),
        "below_threshold_count": len(below),
        "average_compliance_percent": average,
        "users": rows,
    }


@router.get("/users/{user_id}/compliance")
def user_compliance(
    user_id: int,
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Active user not found")
    result = compliance_for_users(db, [user])[user.id]
    threshold = configured_compliance_threshold(db)
    return {
        **result,
        "threshold_percent": threshold,
        "below_threshold": result["compliance_percent"] < threshold,
    }


@router.get("/curriculum-grid")
def curriculum_grid(
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    roles = db.scalars(
        select(JobRole)
        .where(JobRole.is_active.is_(True))
        .order_by(JobRole.department, JobRole.name)
    ).all()
    documents = (
        db.scalars(
            select(DocumentFamily)
            .options(selectinload(DocumentFamily.versions))
            .where(
                DocumentFamily.is_active.is_(True),
                DocumentFamily.document_type == "SOP",
            )
            .order_by(DocumentFamily.code)
        )
        .unique()
        .all()
    )
    role_ids = [role.id for role in roles]
    document_ids = [document.id for document in documents]
    requirements: list[RoleDocumentRequirement] = []
    if role_ids and document_ids:
        requirements = db.scalars(
            select(RoleDocumentRequirement).where(
                RoleDocumentRequirement.job_role_id.in_(role_ids),
                RoleDocumentRequirement.document_family_id.in_(document_ids),
            )
        ).all()
    required = {
        (item.job_role_id, item.document_family_id)
        for item in requirements
        if item.is_active and item.requirement_type in TRAINING_REQUIREMENT_TYPES
    }
    return {
        "roles": [
            {
                "id": role.id,
                "code": role.code,
                "name": role.name,
                "department": role.department,
            }
            for role in roles
        ],
        "documents": [
            {
                "id": document.id,
                "code": document.code,
                "title": document.title,
                "owner_department": document.owner_department,
                "current_version": next(
                    (
                        {
                            "id": version.id,
                            "version_label": version.version_label,
                            "effective_at": version.effective_at,
                        }
                        for version in document.versions
                        if version.status == "RELEASED"
                    ),
                    None,
                ),
                "required_role_ids": [
                    role.id for role in roles if (role.id, document.id) in required
                ],
            }
            for document in documents
        ],
        "default_due_days": configured_due_days(db),
    }


@router.put("/curriculum-grid")
def update_curriculum_grid(
    payload: CurriculumGridUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("training.manage")),
    db: Session = Depends(get_db),
):
    roles = db.scalars(select(JobRole).where(JobRole.is_active.is_(True))).all()
    documents = db.scalars(
        select(DocumentFamily).where(
            DocumentFamily.is_active.is_(True),
            DocumentFamily.document_type == "SOP",
        )
    ).all()
    role_ids = {role.id for role in roles}
    document_ids = {document.id for document in documents}
    target = {(item.job_role_id, item.document_family_id) for item in payload.selected}
    invalid = [pair for pair in target if pair[0] not in role_ids or pair[1] not in document_ids]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail="The curriculum contains an inactive role or a document that is not an active SOP",
        )

    existing = db.scalars(
        select(RoleDocumentRequirement).where(
            RoleDocumentRequirement.job_role_id.in_(role_ids),
            RoleDocumentRequirement.document_family_id.in_(document_ids),
        )
    ).all() if role_ids and document_ids else []
    by_key = {(item.job_role_id, item.document_family_id): item for item in existing}
    before_active = sorted(
        [list(key) for key, item in by_key.items() if item.is_active and item.requirement_type in TRAINING_REQUIREMENT_TYPES]
    )

    added = 0
    reactivated = 0
    retired = 0
    normalised = 0
    assignments_created = 0
    assignments_closed = 0
    due_days = configured_due_days(db)

    for key in sorted(target):
        requirement = by_key.get(key)
        if requirement is None:
            requirement = RoleDocumentRequirement(
                job_role_id=key[0],
                document_family_id=key[1],
                requirement_type="READ_UNDERSTAND",
                due_days=due_days,
                is_active=True,
                reason=payload.reason,
                created_by=auth.user.id,
            )
            db.add(requirement)
            db.flush()
            by_key[key] = requirement
            added += 1
        else:
            if not requirement.is_active:
                reactivated += 1
            if requirement.requirement_type != "READ_UNDERSTAND":
                normalised += 1
            requirement.is_active = True
            requirement.requirement_type = "READ_UNDERSTAND"
            requirement.due_days = requirement.due_days if requirement.due_days is not None else due_days
            requirement.reason = payload.reason
        assignments_created += assign_requirement(db, requirement, assigned_by=auth.user.id)

    for key, requirement in by_key.items():
        if key in target or not requirement.is_active or requirement.requirement_type not in TRAINING_REQUIREMENT_TYPES:
            continue
        requirement.is_active = False
        requirement.reason = payload.reason
        assignments_closed += close_requirement_sources(db, requirement, reason=payload.reason)
        retired += 1

    after_active = sorted([list(key) for key in target])
    record_audit(
        db,
        event_type="ROLE_CURRICULUM_GRID_UPDATED",
        request=request,
        actor=auth,
        entity_type="ROLE_CURRICULUM",
        entity_id="GLOBAL",
        reason=payload.reason,
        before={"active_sop_role_links": before_active},
        after={"active_sop_role_links": after_active},
        metadata={
            "requirements_added": added,
            "requirements_reactivated": reactivated,
            "requirements_retired": retired,
            "requirements_normalised": normalised,
            "training_assignments_created": assignments_created,
            "training_assignments_closed": assignments_closed,
        },
    )
    db.commit()
    return {
        "ok": True,
        "requirements_added": added,
        "requirements_reactivated": reactivated,
        "requirements_retired": retired,
        "requirements_normalised": normalised,
        "training_assignments_created": assignments_created,
        "training_assignments_closed": assignments_closed,
    }


@router.get("/live-matrix")
def live_matrix(
    job_role_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    _: AuthContext = Depends(require_permission("training.view_team")),
    db: Session = Depends(get_db),
):
    users_query = select(User).where(User.is_active.is_(True))
    if job_role_id is not None:
        role = db.get(JobRole, job_role_id)
        if not role or not role.is_active:
            raise HTTPException(status_code=404, detail="Active job role not found")
        users_query = (
            users_query
            .join(UserJobRole, UserJobRole.user_id == User.id)
            .where(
                UserJobRole.job_role_id == job_role_id,
                active_role_condition(),
            )
        )
    else:
        users_query = (
            users_query
            .join(UserJobRole, UserJobRole.user_id == User.id)
            .join(JobRole, JobRole.id == UserJobRole.job_role_id)
            .where(JobRole.is_active.is_(True), active_role_condition())
        )
    if user_id is not None:
        users_query = users_query.where(User.id == user_id)
    users = db.scalars(users_query.order_by(User.display_name)).unique().all()
    if user_id is not None and not users:
        raise HTTPException(status_code=404, detail="Operator is not active in the selected role filter")

    versions = current_sop_versions(db)
    version_ids = [version.id for version, _ in versions]
    user_ids = [user.id for user in users]
    assignments: list[TrainingAssignment] = []
    if version_ids and user_ids:
        assignments = db.scalars(
            select(TrainingAssignment).where(
                TrainingAssignment.user_id.in_(user_ids),
                TrainingAssignment.document_version_id.in_(version_ids),
            )
        ).all()
    assignment_map = {(item.user_id, item.document_version_id): item for item in assignments}
    compliance = compliance_for_users(db, users)

    rows = []
    for version, family in versions:
        cells = []
        for user in users:
            assignment = assignment_map.get((user.id, version.id))
            status = "NOT_ASSIGNED"
            if assignment and assignment.status == "COMPLETED":
                status = "COMPLETED"
            elif assignment and assignment.status == "ASSIGNED":
                status = displayed_status(assignment)
            cells.append(
                {
                    "user_id": user.id,
                    "status": status,
                    "due_at": assignment.due_at if assignment and assignment.status == "ASSIGNED" else None,
                    "completed_at": assignment.completed_at if assignment and assignment.status == "COMPLETED" else None,
                    "individual_assignment": bool(assignment and assignment.is_individual),
                }
            )
        rows.append(
            {
                "document": {
                    "id": family.id,
                    "code": family.code,
                    "title": family.title,
                    "owner_department": family.owner_department,
                },
                "current_version": {
                    "id": version.id,
                    "version_label": version.version_label,
                    "effective_at": version.effective_at,
                },
                "cells": cells,
            }
        )

    return {
        "job_role_id": job_role_id,
        "selected_user_id": user_id,
        "threshold_percent": configured_compliance_threshold(db),
        "users": [
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "compliance_percent": compliance[user.id]["compliance_percent"],
                "required": compliance[user.id]["required"],
                "completed": compliance[user.id]["completed"],
                "overdue": compliance[user.id]["overdue"],
            }
            for user in users
        ],
        "rows": rows,
    }
