from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    AssignmentSource,
    DocumentVersion,
    JobRole,
    RoleDocumentRequirement,
    TrainingAssignment,
    User,
    UserJobRole,
)

TRAINING_REQUIREMENT_TYPES = {"READ_UNDERSTAND", "AWARENESS"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def active_role_condition(today: date | None = None):
    today = today or date.today()
    return and_(
        UserJobRole.effective_from <= today,
        or_(UserJobRole.effective_to.is_(None), UserJobRole.effective_to >= today),
    )


def current_released_version(db: Session, family_id: int) -> DocumentVersion | None:
    return db.scalar(
        select(DocumentVersion)
        .where(DocumentVersion.family_id == family_id, DocumentVersion.status == "RELEASED")
        .order_by(
            DocumentVersion.effective_at.desc().nullslast(),
            DocumentVersion.created_at.desc(),
        )
        .limit(1)
    )


def ensure_assignment(
    db: Session,
    *,
    user_id: int,
    version: DocumentVersion,
    requirement: RoleDocumentRequirement | None,
    due_days: int,
    requirement_type: str,
    assigned_by: int | None,
) -> tuple[TrainingAssignment, bool]:
    assignment = db.scalar(
        select(TrainingAssignment).where(
            TrainingAssignment.user_id == user_id,
            TrainingAssignment.document_version_id == version.id,
        )
    )
    created = assignment is None or (assignment is not None and assignment.status == "CANCELLED")
    if assignment is None:
        assignment = TrainingAssignment(
            user_id=user_id,
            document_version_id=version.id,
            status="ASSIGNED",
            requirement_type=requirement_type,
            is_individual=requirement is None,
            assigned_at=utcnow(),
            due_at=utcnow() + timedelta(days=due_days),
            assigned_by=assigned_by,
        )
        db.add(assignment)
        db.flush()
    elif assignment.status == "CANCELLED":
        assignment.status = "ASSIGNED"
        assignment.requirement_type = requirement_type
        assignment.assigned_at = utcnow()
        assignment.due_at = utcnow() + timedelta(days=due_days)
        assignment.closed_at = None
        assignment.closure_reason = None
        assignment.assigned_by = assigned_by
        if requirement is None:
            assignment.is_individual = True
    elif assignment.status == "ASSIGNED":
        if requirement is None:
            assignment.is_individual = True
        candidate_due = utcnow() + timedelta(days=due_days)
        if candidate_due < as_utc(assignment.due_at):
            assignment.due_at = candidate_due
    if requirement is not None and db.get(AssignmentSource, (assignment.id, requirement.id)) is None:
        db.add(AssignmentSource(assignment_id=assignment.id, requirement_id=requirement.id))
    return assignment, created


def assign_requirement(db: Session, requirement: RoleDocumentRequirement, *, assigned_by: int | None) -> int:
    if not requirement.is_active or requirement.requirement_type not in TRAINING_REQUIREMENT_TYPES:
        return 0
    role = db.get(JobRole, requirement.job_role_id)
    if not role or not role.is_active:
        return 0
    version = current_released_version(db, requirement.document_family_id)
    if version is None:
        return 0
    user_ids = db.scalars(
        select(UserJobRole.user_id)
        .join(User, User.id == UserJobRole.user_id)
        .where(
            UserJobRole.job_role_id == requirement.job_role_id,
            active_role_condition(),
            User.is_active.is_(True),
        )
    ).all()
    created = 0
    for user_id in set(user_ids):
        _, was_created = ensure_assignment(
            db,
            user_id=user_id,
            version=version,
            requirement=requirement,
            due_days=requirement.due_days,
            requirement_type=requirement.requirement_type,
            assigned_by=assigned_by,
        )
        created += int(was_created)
    return created


def assign_user_for_job_role(db: Session, user_id: int, job_role_id: int, *, assigned_by: int | None) -> int:
    role = db.get(JobRole, job_role_id)
    if not role or not role.is_active:
        return 0
    requirements = db.scalars(
        select(RoleDocumentRequirement).where(
            RoleDocumentRequirement.job_role_id == job_role_id,
            RoleDocumentRequirement.is_active.is_(True),
        )
    ).all()
    created = 0
    for requirement in requirements:
        if requirement.requirement_type not in TRAINING_REQUIREMENT_TYPES:
            continue
        version = current_released_version(db, requirement.document_family_id)
        if version is None:
            continue
        _, was_created = ensure_assignment(
            db,
            user_id=user_id,
            version=version,
            requirement=requirement,
            due_days=requirement.due_days,
            requirement_type=requirement.requirement_type,
            assigned_by=assigned_by,
        )
        created += int(was_created)
    return created


def reconcile_active_role_assignments(db: Session, *, assigned_by: int | None = None) -> int:
    """Create assignments when a future-dated job-role link becomes effective.

    The operation is idempotent because ``ensure_assignment`` de-duplicates on
    user and controlled-document version.
    """
    links = db.scalars(
        select(UserJobRole)
        .join(User, User.id == UserJobRole.user_id)
        .join(JobRole, JobRole.id == UserJobRole.job_role_id)
        .where(
            active_role_condition(),
            User.is_active.is_(True),
            JobRole.is_active.is_(True),
        )
    ).all()
    created = 0
    for link in links:
        created += assign_user_for_job_role(
            db,
            link.user_id,
            link.job_role_id,
            assigned_by=assigned_by,
        )
    return created


def reconcile_assignment_sources(db: Session) -> int:
    """Remove ended role sources and close assignments no longer required by any source."""
    assignments = db.scalars(select(TrainingAssignment).where(TrainingAssignment.status == "ASSIGNED")).all()
    closed = 0
    for assignment in assignments:
        sources = db.scalars(select(AssignmentSource).where(AssignmentSource.assignment_id == assignment.id)).all()
        if not sources:
            continue
        removed = False
        for source in sources:
            requirement = db.get(RoleDocumentRequirement, source.requirement_id)
            has_active_role = False
            role = db.get(JobRole, requirement.job_role_id) if requirement else None
            if requirement and requirement.is_active and role and role.is_active:
                has_active_role = (
                    db.scalar(
                        select(UserJobRole.id)
                        .join(User, User.id == UserJobRole.user_id)
                        .where(
                            UserJobRole.user_id == assignment.user_id,
                            UserJobRole.job_role_id == requirement.job_role_id,
                            active_role_condition(),
                            User.is_active.is_(True),
                        )
                        .limit(1)
                    )
                    is not None
                )
            if not has_active_role:
                db.delete(source)
                removed = True
        if not removed:
            continue
        db.flush()
        remaining = db.scalar(
            select(func.count(AssignmentSource.requirement_id)).where(AssignmentSource.assignment_id == assignment.id)
        )
        if not remaining and not assignment.is_individual:
            assignment.status = "CANCELLED"
            assignment.closed_at = utcnow()
            assignment.closure_reason = "No active job-role requirement remains"
            closed += 1
    return closed


def assign_released_version(db: Session, version: DocumentVersion, *, assigned_by: int | None) -> int:
    if version.training_impact != "RETRAIN":
        return 0
    requirements = db.scalars(
        select(RoleDocumentRequirement)
        .join(JobRole, JobRole.id == RoleDocumentRequirement.job_role_id)
        .where(
            RoleDocumentRequirement.document_family_id == version.family_id,
            RoleDocumentRequirement.is_active.is_(True),
            JobRole.is_active.is_(True),
        )
    ).all()
    created = 0
    for requirement in requirements:
        if requirement.requirement_type not in TRAINING_REQUIREMENT_TYPES:
            continue
        user_ids = db.scalars(
            select(UserJobRole.user_id)
            .join(User, User.id == UserJobRole.user_id)
            .where(
                UserJobRole.job_role_id == requirement.job_role_id,
                active_role_condition(),
                User.is_active.is_(True),
            )
        ).all()
        for user_id in set(user_ids):
            _, was_created = ensure_assignment(
                db,
                user_id=user_id,
                version=version,
                requirement=requirement,
                due_days=requirement.due_days,
                requirement_type=requirement.requirement_type,
                assigned_by=assigned_by,
            )
            created += int(was_created)
    return created


def cancel_incomplete_for_superseded_version(db: Session, version_id: int, *, reason: str) -> int:
    assignments = db.scalars(
        select(TrainingAssignment).where(
            TrainingAssignment.document_version_id == version_id,
            TrainingAssignment.status == "ASSIGNED",
        )
    ).all()
    now = utcnow()
    for assignment in assignments:
        assignment.status = "CANCELLED"
        assignment.closed_at = now
        assignment.closure_reason = reason
    return len(assignments)


def displayed_status(assignment: TrainingAssignment) -> str:
    if assignment.status == "ASSIGNED" and as_utc(assignment.due_at) < utcnow():
        return "OVERDUE"
    return assignment.status
