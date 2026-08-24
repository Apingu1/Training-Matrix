from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from .audit import record_audit
from .database import runtime
from .models import AuthSession, User
from .security import hash_password, utcnow
from .services.backup import create_backup


def reset_password(username: str, password: str, reason: str) -> None:
    with runtime.session() as db:
        user = db.scalar(select(User).where(User.username == username.lower()))
        if not user:
            raise SystemExit(f"User not found: {username}")
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.is_active = True
        user.failed_login_count = 0
        user.locked_until = None
        sessions = db.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        ).all()
        for session in sessions:
            session.revoked_at = utcnow()
        record_audit(
            db,
            event_type="PASSWORD_RESET_BY_SERVER_TOOL",
            actor_username="SERVER_ADMIN",
            entity_type="USER",
            entity_id=user.id,
            reason=reason,
            metadata={"sessions_revoked": len(sessions)},
        )
        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Eaststone Training Matrix server administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reset = subparsers.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    password_group = reset.add_mutually_exclusive_group(required=True)
    password_group.add_argument("--password")
    password_group.add_argument("--password-stdin", action="store_true")
    reset.add_argument("--reason", default="Emergency server-side password reset")
    backup = subparsers.add_parser("create-backup")
    backup.add_argument("--type", default="SERVER_TOOL")
    backup.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "reset-password":
        password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else args.password
        if not password:
            raise SystemExit("A non-empty password is required")
        reset_password(args.username, password, args.reason)
    elif args.command == "create-backup":
        with runtime.session() as db:
            run = create_backup(
                db,
                backup_type=args.type,
                reason=args.reason,
                created_by=None,
            )
            record_audit(
                db,
                event_type="SERVER_BACKUP_CREATED" if run.status == "COMPLETE" else "SERVER_BACKUP_FAILED",
                actor_username="SERVER_ADMIN",
                entity_type="BACKUP",
                entity_id=run.id,
                success=run.status == "COMPLETE",
                reason=args.reason,
                metadata={"filename": run.filename, "backup_type": run.backup_type},
            )
            db.commit()
            if run.status != "COMPLETE":
                raise SystemExit(run.error_message or "Backup failed")
            print(run.filename)


if __name__ == "__main__":
    main()
