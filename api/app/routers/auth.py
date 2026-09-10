from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import settings
from ..database import get_db
from ..models import AuthSession, JobRole, SecurityRole, User, UserJobRole
from ..schemas import LoginRequest, PasswordChangeRequest
from ..security import (
    AuthContext,
    as_utc,
    create_access_token,
    get_current_auth,
    hash_password,
    new_session,
    session_absolute_minutes,
    session_idle_minutes,
    utcnow,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    now = utcnow()
    if user and user.locked_until and as_utc(user.locked_until) > now:
        record_audit(
            db,
            event_type="LOGIN_FAILED_LOCKED",
            request=request,
            actor=user,
            entity_type="USER",
            entity_id=user.id,
            success=False,
            reason="Account temporarily locked",
        )
        db.commit()
        raise HTTPException(status_code=423, detail="Account temporarily locked after repeated failures")

    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
        record_audit(
            db,
            event_type="LOGIN_FAILED",
            request=request,
            actor=user,
            actor_username=username,
            entity_type="USER",
            entity_id=user.id if user else None,
            success=False,
            reason="Invalid credentials or inactive account",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    auth_session = new_session(user, request, db)
    db.add(auth_session)
    record_audit(
        db,
        event_type="LOGIN_SUCCESS",
        request=request,
        actor=user,
        entity_type="AUTH_SESSION",
        entity_id=auth_session.id,
    )
    db.commit()
    return {
        "access_token": create_access_token(user, auth_session),
        "token_type": "bearer",
        "expires_at": auth_session.expires_at,
        "must_change_password": user.must_change_password,
    }


@router.get("/me")
def me(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    role = db.get(SecurityRole, auth.user.security_role_id)
    today = utcnow().date()
    job_roles = (
        db.execute(
            select(JobRole.id, JobRole.code, JobRole.name, JobRole.department)
            .join(UserJobRole, UserJobRole.job_role_id == JobRole.id)
            .where(
                UserJobRole.user_id == auth.user.id,
                UserJobRole.effective_from <= today,
                or_(
                    UserJobRole.effective_to.is_(None),
                    UserJobRole.effective_to >= today,
                ),
            )
            .order_by(JobRole.department, JobRole.name)
        )
        .mappings()
        .all()
    )
    absolute_minutes = session_absolute_minutes(db)
    absolute_expiry = min(
        as_utc(auth.session.expires_at),
        as_utc(auth.session.issued_at) + timedelta(minutes=absolute_minutes),
    )
    return {
        "id": auth.user.id,
        "username": auth.user.username,
        "display_name": auth.user.display_name,
        "email": auth.user.email,
        "security_role": {"id": role.id, "code": role.code, "name": role.name},
        "permissions": sorted(auth.permissions),
        "job_roles": [dict(row) for row in job_roles],
        "must_change_password": auth.user.must_change_password,
        "session_idle_minutes": session_idle_minutes(db),
        "session_absolute_minutes": absolute_minutes,
        "session_expires_at": absolute_expiry,
    }


@router.get("/session-settings")
def session_settings(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    return {
        "inactivity_timeout_minutes": session_idle_minutes(db),
        "absolute_timeout_minutes": session_absolute_minutes(db),
        "expires_at": min(
            as_utc(auth.session.expires_at),
            as_utc(auth.session.issued_at) + timedelta(minutes=session_absolute_minutes(db)),
        ),
    }


@router.post("/activity")
def activity(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    auth.session.last_activity_at = utcnow()
    db.commit()
    return {"ok": True, "last_activity_at": auth.session.last_activity_at}


@router.post("/logout")
def logout(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    auth.session.revoked_at = utcnow()
    record_audit(
        db,
        event_type="LOGOUT",
        request=request,
        actor=auth,
        entity_type="AUTH_SESSION",
        entity_id=auth.session.id,
    )
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, auth.user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if verify_password(payload.new_password, auth.user.password_hash):
        raise HTTPException(status_code=400, detail="The new password must be different")
    try:
        auth.user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.user.must_change_password = False
    sessions = db.scalars(
        select(AuthSession).where(AuthSession.user_id == auth.user.id, AuthSession.revoked_at.is_(None))
    ).all()
    for session in sessions:
        session.revoked_at = utcnow()
    record_audit(
        db,
        event_type="PASSWORD_CHANGED",
        request=request,
        actor=auth,
        entity_type="USER",
        entity_id=auth.user.id,
        metadata={"sessions_revoked": len(sessions)},
    )
    db.commit()
    return {"ok": True, "reauthentication_required": True}
