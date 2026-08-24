# Stock Control feature review and carry-over

The Training Matrix follows the mature operational patterns in Eaststone Stock Control while keeping document-control and training logic in a separate bounded application. This avoids coupling stock transactions to controlled-document records.

## Carried over

| Stock Control capability | Training Matrix implementation |
|---|---|
| FastAPI API and React/TypeScript interface | Same deployment shape and operator-friendly responsive layout |
| PostgreSQL authoritative data store | Normalised controlled-document, user, training and audit records |
| Docker server deployment | Database, migration, API, web and backup-scheduler services |
| User login and forced initial password change | Argon2 passwords, strong policy and one-time temporary credentials |
| Server-side sessions and inactivity control | Signed access token plus revocable database session and 15-minute default idle timeout |
| Failed-login protection | Configurable lockout threshold and duration, with audit events |
| Role-based access control | Dynamic permission matrix with seeded least-privilege roles |
| Admin-managed users | Create, amend, deactivate, reset password and revoke sessions |
| Append-oriented audit trail | Before/after/reason/actor/time/request/IP metadata; DB triggers prevent mutation |
| Backup administration | Automatic/manual PostgreSQL dumps, manifests, verification, download/upload and staged restore |
| Maintenance mode | Ordinary write operations pause during controlled maintenance/restore |
| Windows server operation | Install/start/stop/status/update/configure/reset/uninstall scripts |
| Health checks and production proxy | Container health checks, Nginx security headers and API proxy |
| Progressive schema changes | Alembic migration runs before the API starts |
| PWA-style operator access | Installable web manifest and responsive navigation |

## Adapted for this domain

| Concern | Training Matrix design |
|---|---|
| Stock item/revision | Document family and immutable document version |
| Stock movement approval | Review, independent approval, release and electronic signature |
| Transaction attribution | Training assignment and signed acknowledgement |
| Department/permission scope | Job role curriculum plus security role permissions |
| Current quantity/status | Live compliance state calculated from the current effective version |
| Historical ledger | Superseded revisions, cancelled old assignments and immutable acknowledgement history |

## Deliberately not copied

- Inventory, lot, expiry, supplier, stock movement and reconciliation domain objects.
- Any direct dependency on the Stock Control database.
- Browser-supplied permission or identity decisions.
- Spreadsheet cell codes as the source of truth.
- The unused `t` trainer marker.
- Destructive in-place restore or update behaviour.

## Improvements made while carrying the pattern over

- Approval separation prevents a revision creator approving the same revision.
- File identity is bound to a SHA-256 fingerprint throughout view, signature and acknowledgement.
- Shared-folder traversal and symlink escape are rejected.
- Restore happens into a new PostgreSQL dataset and activates only after verification and sanity checks; the previous dataset is retained.
- Core security roles cannot be retired and the last administrator cannot be disabled or demoted.
- Training generated from multiple job roles is de-duplicated per user and document version while retaining requirement sources.
