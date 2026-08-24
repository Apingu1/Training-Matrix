# Eaststone Training Matrix

Eaststone Training Matrix is an on-premises controlled-document and read-and-understand training platform. It keeps the approved PDF/DOCX files in Eaststone's existing shared server folder and stores only control metadata, exact SHA-256 fingerprints, permissions, curricula, assignments, acknowledgements and audit history in PostgreSQL.

The first release is intentionally a clean build. It does **not** import the current master spreadsheet; migration can be designed and verified separately.

## Included in this build

- Controlled-document master list with document families and immutable revision history.
- Read-only PDF viewer for operators; DOCX files are converted to a disposable PDF rendition.
- Server-folder browser constrained to the configured read-only document root.
- SHA-256 change detection: a controlled source changed outside the workflow is blocked.
- Draft, review, independent approval, scheduled/effective release, supersession and obsolescence states.
- Electronic approval/release signatures with password re-authentication and exact file hash.
- Role-based curricula, effective-dated operator roles, automatic assignments and retraining on revision.
- Operator read-and-understood acknowledgement after verified document viewing and password re-authentication.
- Live role matrix and user history with plain-language statuses such as Reading required, Read and acknowledged, Reading overdue and Closed before completion.
- Controlled-copy issue, return and destruction register.
- Dynamic security roles and permissions, idle sessions, lockout, forced first-login password change and server-side enforcement.
- Append-only audit, acknowledgement and document-signature records in PostgreSQL.
- Searchable audit trail with CSV/PDF export.
- Automatic/manual PostgreSQL backups, hash manifests, verification and staged restore with a pre-restore safety backup.
- Docker-based server deployment, Windows administration scripts and CI checks.

## Quick start for development

The simplest Codespaces/Linux development start is:

```bash
./run_stack.sh
```

On first use, the script creates a private development `.env`, local document/backup folders and a development TLS certificate. It then builds the Docker stack, migrates/seeds the database, waits for health and prints the preview URL and one-time admin password. Re-running it preserves the named database volumes and existing data.

For non-container test execution, requirements are Python 3.12+, Node 22+ and LibreOffice for local DOCX rendition tests.

```bash
python -m venv .venv
.venv/bin/pip install -r api/requirements-dev.txt
cd web && npm ci && cd ..
APP_ENV=test .venv/bin/pytest -q api/tests
cd web && npm run build
```

For a server installation, follow [Installation](docs/INSTALLATION.md). Do not use `.env.example` unchanged: production secrets and host paths must be generated/configured first.

## Documentation

- [User requirements and acceptance criteria](docs/USER_REQUIREMENTS.md)
- [Architecture and data model](docs/ARCHITECTURE.md)
- [Stock Control feature review](docs/STOCK_CONTROL_FEATURE_REVIEW.md)
- [Installation and Windows operations](docs/INSTALLATION.md)
- [Backup and recovery](docs/BACKUP_AND_RECOVERY.md)
- [Security and validation plan](docs/SECURITY_AND_VALIDATION.md)

## Important operating boundary

Application backups include database state and an inventory of external document paths/hashes; they do not copy the controlled PDF/DOCX files. The shared document folder must therefore have its own access controls, version-aware filesystem backup and tested restore procedure. See [Backup and recovery](docs/BACKUP_AND_RECOVERY.md).

## Release status

This repository provides an implementation and automated software tests. It is not, by itself, a validated production system. Eaststone must complete documented configuration approval, IQ/OQ/PQ or equivalent risk-based validation, UAT, backup-restore evidence, SOP updates and release authorisation before regulated use.
