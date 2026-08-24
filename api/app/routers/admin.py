from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import model_snapshot, record_audit
from ..database import get_db
from ..models import (
    AuthSession,
    JobRole,
    Permission,
    RolePermission,
    SecurityRole,
    User,
    UserJobRole,
)
from ..schemas import (
    JobRoleCreate,
    JobRoleUpdate,
    PasswordResetRequest,
    SecurityRoleCreate,
    SecurityRoleUpdate,
    UserCreate,
    UserJobRoleCreate,
    UserJobRoleEnd,
    UserUpdate,
)
from ..security import AuthContext, hash_password, require_any_permission, require_permission, utcnow
from ..services.training import (
    active_role_condition,
    assign_user_for_job_role,
    reconcile_assignment_sources,
)

router = APIRouter(prefix="/admin", tags=["Administration"])
CORE_SECURITY_ROLES = {
    "ADMIN",
    "QA_APPROVER",
    "DOCUMENT_CONTROLLER",
    "MANAGER_TRAINER",
    "OPERATOR",
    "AUDITOR",
}


def user_dict(user: User, db: Session) -> dict:
    role = db.get(SecurityRole, user.security_role_id)
    job_roles = (
        db.execute(
            select(
                UserJobRole.id,
                UserJobRole.effective_from,
                UserJobRole.effective_to,
                JobRole.id.label("job_role_id"),
                JobRole.code,
                JobRole.name,
                JobRole.department,
            )
            .join(JobRole, JobRole.id == UserJobRole.job_role_id)
            .where(UserJobRole.user_id == user.id)
            .order_by(UserJobRole.effective_to.nullsfirst(), JobRole.department, JobRole.name)
        )
        .mappings()
        .all()
    )
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
        "security_role": {"id": role.id, "code": role.code, "name": role.name} if role else None,
        "job_roles": [dict(item) for item in job_roles],
        "created_at": user.created_at,
    }


@router.get("/permissions")
def list_permissions(
    _: AuthContext = Depends(require_permission("security_roles.manage")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Permission).order_by(Permission.category, Permission.name)).all()
    return [
        {
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "category": row.category,
        }
        for row in rows
    ]


@router.get("/security-roles")
def list_security_roles(
    _: AuthContext = Depends(require_any_permission("users.manage", "security_roles.manage")),
    db: Session = Depends(get_db),
):
    roles = db.scalars(select(SecurityRole).order_by(SecurityRole.name)).all()
    return [
        {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "is_active": role.is_active,
            "permission_codes": sorted(
                db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)).all()
            ),
        }
        for role in roles
    ]


@router.post("/security-roles", status_code=201)
def create_security_role(
    payload: SecurityRoleCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("security_roles.manage")),
    db: Session = Depends(get_db),
):
    unknown = set(payload.permission_codes) - set(db.scalars(select(Permission.code)).all())
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permissions: {', '.join(sorted(unknown))}")
    role = SecurityRole(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        is_system=False,
    )
    db.add(role)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Security role code already exists") from exc
    for code in set(payload.permission_codes):
        db.add(RolePermission(role_id=role.id, permission_code=code))
    record_audit(
        db,
        event_type="SECURITY_ROLE_CREATED",
        request=request,
        actor=auth,
        entity_type="SECURITY_ROLE",
        entity_id=role.id,
        reason=payload.reason,
        after={
            "code": role.code,
            "name": role.name,
            "permissions": sorted(set(payload.permission_codes)),
        },
    )
    db.commit()
    return {"id": role.id}


@router.patch("/security-roles/{role_id}")
def update_security_role(
    role_id: int,
    payload: SecurityRoleUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("security_roles.manage")),
    db: Session = Depends(get_db),
):
    role = db.get(SecurityRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Security role not found")
    if role.code in CORE_SECURITY_ROLES and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Built-in security roles cannot be retired")
    if payload.is_active is False:
        assigned_users = db.scalar(
            select(func.count(User.id)).where(
                User.security_role_id == role.id,
                User.is_active.is_(True),
            )
        )
        if assigned_users:
            raise HTTPException(
                status_code=409,
                detail="Reassign active users before retiring this security role",
            )
    before = {
        **model_snapshot(role),
        "permissions": sorted(
            db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)).all()
        ),
    }
    for field in ("name", "description", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(role, field, value)
    if payload.permission_codes is not None:
        desired = set(payload.permission_codes)
        unknown = desired - set(db.scalars(select(Permission.code)).all())
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown permissions: {', '.join(sorted(unknown))}",
            )
        if role.code == "ADMIN":
            desired = set(db.scalars(select(Permission.code)).all())
        existing = set(
            db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)).all()
        )
        for code in desired - existing:
            db.add(RolePermission(role_id=role.id, permission_code=code))
        for code in existing - desired:
            mapping = db.get(RolePermission, (role.id, code))
            if mapping:
                db.delete(mapping)
    db.flush()
    after = {
        **model_snapshot(role),
        "permissions": sorted(
            db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)).all()
        ),
    }
    record_audit(
        db,
        event_type="SECURITY_ROLE_UPDATED",
        request=request,
        actor=auth,
        entity_type="SECURITY_ROLE",
        entity_id=role.id,
        reason=payload.reason,
        before=before,
        after=after,
    )
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(
    _: AuthContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    return [user_dict(user, db) for user in db.scalars(select(User).order_by(User.display_name)).all()]


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    role = db.get(SecurityRole, payload.security_role_id)
    if not role or not role.is_active:
        raise HTTPException(status_code=400, detail="Select an active security role")
    try:
        password_hash = hash_password(payload.temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = User(
        username=payload.username.lower(),
        display_name=payload.display_name,
        email=payload.email,
        password_hash=password_hash,
        security_role_id=role.id,
        must_change_password=True,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    assignment_count = 0
    for job_role_id in set(payload.job_role_ids):
        job_role = db.get(JobRole, job_role_id)
        if not job_role or not job_role.is_active:
            raise HTTPException(status_code=400, detail=f"Job role {job_role_id} is not active")
        db.add(
            UserJobRole(
                user_id=user.id,
                job_role_id=job_role.id,
                effective_from=date.today(),
                assigned_by=auth.user.id,
                reason=payload.reason,
            )
        )
        db.flush()
        assignment_count += assign_user_for_job_role(db, user.id, job_role.id, assigned_by=auth.user.id)
    record_audit(
        db,
        event_type="USER_CREATED",
        request=request,
        actor=auth,
        entity_type="USER",
        entity_id=user.id,
        reason=payload.reason,
        after={
            "username": user.username,
            "display_name": user.display_name,
            "security_role": role.code,
            "job_role_ids": payload.job_role_ids,
        },
        metadata={"training_assignments_created": assignment_count},
    )
    db.commit()
    return user_dict(user, db)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    before = model_snapshot(user, exclude={"password_hash"})
    existing_role = db.get(SecurityRole, user.security_role_id)
    if (
        existing_role
        and existing_role.code == "ADMIN"
        and (payload.is_active is False or (payload.security_role_id and payload.security_role_id != existing_role.id))
    ):
        active_admins = db.scalar(
            select(func.count(User.id)).join(SecurityRole).where(User.is_active.is_(True), SecurityRole.code == "ADMIN")
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=400,
                detail="The last active administrator cannot be disabled or demoted",
            )
    if payload.security_role_id is not None:
        role = db.get(SecurityRole, payload.security_role_id)
        if not role or not role.is_active:
            raise HTTPException(status_code=400, detail="Select an active security role")
        user.security_role_id = role.id
    for field in ("display_name", "email", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(user, field, value)
    assignments_created = 0
    assignments_closed = 0
    if payload.is_active is True:
        active_job_role_ids = db.scalars(
            select(UserJobRole.job_role_id).where(
                UserJobRole.user_id == user.id,
                active_role_condition(),
            )
        ).all()
        for job_role_id in set(active_job_role_ids):
            assignments_created += assign_user_for_job_role(
                db,
                user.id,
                job_role_id,
                assigned_by=auth.user.id,
            )
    elif payload.is_active is False:
        db.flush()
        assignments_closed = reconcile_assignment_sources(db)
    revoked = 0
    if payload.is_active is False or payload.security_role_id is not None:
        sessions = db.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        ).all()
        for session in sessions:
            session.revoked_at = utcnow()
        revoked = len(sessions)
    record_audit(
        db,
        event_type="USER_UPDATED",
        request=request,
        actor=auth,
        entity_type="USER",
        entity_id=user.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(user, exclude={"password_hash"}),
        metadata={
            "sessions_revoked": revoked,
            "training_assignments_created": assignments_created,
            "training_assignments_closed": assignments_closed,
        },
    )
    db.commit()
    return user_dict(user, db)


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    auth: AuthContext = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        user.password_hash = hash_password(payload.temporary_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.must_change_password = True
    user.failed_login_count = 0
    user.locked_until = None
    sessions = db.scalars(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    ).all()
    for session in sessions:
        session.revoked_at = utcnow()
    record_audit(
        db,
        event_type="PASSWORD_RESET_BY_ADMIN",
        request=request,
        actor=auth,
        entity_type="USER",
        entity_id=user.id,
        reason=payload.reason,
        metadata={"sessions_revoked": len(sessions)},
    )
    db.commit()
    return {"ok": True}


@router.get("/job-roles")
def list_job_roles(
    _: AuthContext = Depends(require_any_permission("documents.view", "job_roles.manage", "training.view_team")),
    db: Session = Depends(get_db),
):
    roles = db.scalars(select(JobRole).order_by(JobRole.department, JobRole.name)).all()
    return [model_snapshot(role) for role in roles]


@router.post("/job-roles", status_code=201)
def create_job_role(
    payload: JobRoleCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("job_roles.manage")),
    db: Session = Depends(get_db),
):
    role = JobRole(
        code=payload.code,
        name=payload.name,
        department=payload.department,
        description=payload.description,
    )
    db.add(role)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Job role code already exists") from exc
    record_audit(
        db,
        event_type="JOB_ROLE_CREATED",
        request=request,
        actor=auth,
        entity_type="JOB_ROLE",
        entity_id=role.id,
        reason=payload.reason,
        after=model_snapshot(role),
    )
    db.commit()
    return model_snapshot(role)


@router.patch("/job-roles/{role_id}")
def update_job_role(
    role_id: int,
    payload: JobRoleUpdate,
    request: Request,
    auth: AuthContext = Depends(require_permission("job_roles.manage")),
    db: Session = Depends(get_db),
):
    role = db.get(JobRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    before = model_snapshot(role)
    for field in ("name", "department", "description", "is_active"):
        value = getattr(payload, field)
        if value is not None:
            setattr(role, field, value)
    assignments_closed = 0
    assignments_created = 0
    if payload.is_active is False:
        db.flush()
        assignments_closed = reconcile_assignment_sources(db)
    elif payload.is_active is True:
        user_ids = db.scalars(
            select(UserJobRole.user_id).where(
                UserJobRole.job_role_id == role.id,
                active_role_condition(),
            )
        ).all()
        for user_id in set(user_ids):
            assignments_created += assign_user_for_job_role(
                db,
                user_id,
                role.id,
                assigned_by=auth.user.id,
            )
    record_audit(
        db,
        event_type="JOB_ROLE_UPDATED",
        request=request,
        actor=auth,
        entity_type="JOB_ROLE",
        entity_id=role.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(role),
        metadata={
            "training_assignments_created": assignments_created,
            "training_assignments_closed": assignments_closed,
        },
    )
    db.commit()
    return model_snapshot(role)


@router.post("/users/{user_id}/job-roles", status_code=201)
def assign_job_role(
    user_id: int,
    payload: UserJobRoleCreate,
    request: Request,
    auth: AuthContext = Depends(require_permission("job_roles.manage")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    role = db.get(JobRole, payload.job_role_id)
    if not user or not user.is_active or not role or not role.is_active:
        raise HTTPException(status_code=404, detail="Active user or job role not found")
    overlapping = db.scalar(
        select(UserJobRole).where(
            UserJobRole.user_id == user_id,
            UserJobRole.job_role_id == role.id,
            or_(
                UserJobRole.effective_to.is_(None),
                UserJobRole.effective_to >= payload.effective_from,
            ),
        )
    )
    if overlapping:
        raise HTTPException(
            status_code=409,
            detail="This user already has an overlapping assignment to that job role",
        )
    link = UserJobRole(
        user_id=user_id,
        job_role_id=role.id,
        effective_from=payload.effective_from,
        assigned_by=auth.user.id,
        reason=payload.reason,
    )
    db.add(link)
    db.flush()
    created = 0
    if payload.effective_from <= date.today():
        created = assign_user_for_job_role(db, user.id, role.id, assigned_by=auth.user.id)
    record_audit(
        db,
        event_type="USER_JOB_ROLE_ASSIGNED",
        request=request,
        actor=auth,
        entity_type="USER_JOB_ROLE",
        entity_id=link.id,
        reason=payload.reason,
        after=model_snapshot(link),
        metadata={"training_assignments_created": created},
    )
    db.commit()
    return {"id": link.id, "training_assignments_created": created}


@router.post("/user-job-roles/{link_id}/end")
def end_job_role(
    link_id: int,
    payload: UserJobRoleEnd,
    request: Request,
    auth: AuthContext = Depends(require_permission("job_roles.manage")),
    db: Session = Depends(get_db),
):
    link = db.get(UserJobRole, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="User job-role assignment not found")
    if payload.effective_to < link.effective_from:
        raise HTTPException(status_code=400, detail="End date cannot precede the effective date")
    before = model_snapshot(link)
    link.effective_to = payload.effective_to
    link.reason = payload.reason
    record_audit(
        db,
        event_type="USER_JOB_ROLE_ENDED",
        request=request,
        actor=auth,
        entity_type="USER_JOB_ROLE",
        entity_id=link.id,
        reason=payload.reason,
        before=before,
        after=model_snapshot(link),
    )
    db.commit()
    return {"ok": True}
