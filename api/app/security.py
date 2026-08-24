from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, RolePermission, SecurityRole, User

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate_password_strength(password: str) -> None:
    failures: list[str] = []
    if len(password) < 12:
        failures.append("at least 12 characters")
    if not re.search(r"[A-Z]", password):
        failures.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        failures.append("a lowercase letter")
    if not re.search(r"[0-9]", password):
        failures.append("a number")
    if not re.search(r"[^A-Za-z0-9]", password):
        failures.append("a special character")
    if failures:
        raise ValueError("Password must contain " + ", ".join(failures))


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user: User, session: AuthSession) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "sid": session.id,
        "iat": int(session.issued_at.timestamp()),
        "exp": int(session.expires_at.timestamp()),
        "iss": "eaststone-training-matrix",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def new_session(user: User, request: Request) -> AuthSession:
    now = utcnow()
    return AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        issued_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(minutes=settings.jwt_expires_minutes),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500],
    )


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return request.client.host[:80] if request.client else None


def permissions_for_role(db: Session, role_id: int) -> set[str]:
    return set(db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role_id)).all())


@dataclass(slots=True)
class AuthContext:
    user: User
    session: AuthSession
    permissions: set[str]

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return authorization.split(" ", 1)[1].strip()


def get_current_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    token = _bearer_token(authorization)
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer="eaststone-training-matrix",
        )
        user_id = int(payload["sub"])
        session_id = str(payload["sid"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from exc

    auth_session = db.get(AuthSession, session_id)
    user = db.get(User, user_id)
    now = utcnow()
    if not auth_session or auth_session.user_id != user_id or auth_session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is inactive")
    if as_utc(auth_session.expires_at) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired")
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if as_utc(auth_session.last_activity_at) + idle_limit <= now:
        auth_session.revoked_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session ended due to inactivity",
        )
    role = db.get(SecurityRole, user.security_role_id)
    if not role or not role.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assigned security role is inactive",
        )
    return AuthContext(user=user, session=auth_session, permissions=permissions_for_role(db, role.id))


def require_permission(permission: str) -> Callable:
    def dependency(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if auth.user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Change the temporary password before using this function",
            )
        if permission not in auth.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission}",
            )
        return auth

    return dependency


def require_any_permission(*permissions: str) -> Callable:
    def dependency(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if auth.user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Change the temporary password before using this function",
            )
        if not auth.permissions.intersection(permissions):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return auth

    return dependency
