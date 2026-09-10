# Architecture

## Deployment topology

```mermaid
flowchart TD
    Client["Operator browser"] --> Web["Nginx + React"]
    Web --> API["FastAPI application"]
    API --> DB[("PostgreSQL")]
    API --> Docs["Shared documents folder\nread-only mount"]
    API --> Cache["Disposable DOCX/PDF cache"]
    API --> SMTP["Approved SMTP service"]
    Scheduler["Backup scheduler"] --> DB
    Scheduler --> Backups["External backup folder"]
```

The shared folder remains authoritative for PDF/DOCX content. The application stores a relative path, size, modified time and SHA-256 fingerprint. The Docker mount is read-only, so creation or amendment of source documents remains in Eaststone's existing controlled shared-folder process.

## Controlled-source discovery and baseline

The source-discovery service walks the configured root recursively without following directory/file links and without copying content. A safety limit of 50,000 files bounds a scan. Supported files are hashed; unchanged size/modified-time entries reuse the prior fingerprint on later scans. Unsupported files are inventoried but cannot be imported.

| Classification | Meaning |
|---|---|
| Registered | Relative path and SHA-256 match a controlled version |
| Unregistered | Supported source has no conflicting registered or discovered identity |
| Duplicate | Content, inferred document/version, or a registered identity is duplicated |
| Changed | A registered relative path now has different content |
| Missing | A previously inventoried path is no longer present |
| Unsupported | File extension is not PDF/DOCX |
| Scan error | A supported file could not be inspected safely |

`SourceScanRun` stores trigger, status, counts, warnings and inventory fingerprint; `SourceInventoryFile` stores the persistent per-path observation and inferred metadata. A controller may correct suggestions in the browser. The baseline endpoint requires document-management plus approval permission, password re-authentication and an exact confirmation phrase. It verifies the latest inventory and re-hashes every source before directly creating a `RELEASED` initial version. This direct-release path is deliberately limited to the initial externally approved baseline and records an immutable signature, one audit event per document and a batch digest. Later revisions use the normal independent lifecycle.

## Document lifecycle

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> InReview: Submit
    InReview --> Draft: Return
    InReview --> Approved: Independent approval
    Approved --> Draft: Return
    Approved --> IssuedNotEffective: Future release
    Approved --> Released: Effective release
    IssuedNotEffective --> Released: Effective date
    Released --> Superseded: Replacement activates
    Released --> Obsolete: QA action
    IssuedNotEffective --> Obsolete: QA action
```

An authorised controller can refresh the file fingerprint only while a version is `DRAFT`. Submission, approval, release, viewing and acknowledgement re-check the current source hash. A mismatch after draft control blocks the operation and creates an audit event.

## Training derivation

1. A job role is assigned one or more active document-family requirements.
2. A user receives effective-dated job roles.
3. When a released version becomes effective, each active in-scope user receives one assignment for that exact version.
4. Multiple roles requiring the same version produce one assignment with multiple requirement sources.
5. A view event for the exact file hash must exist before acknowledgement.
6. Password re-authentication creates an immutable acknowledgement bound to user, session, assignment, version and SHA-256.
7. A replacement version supersedes the old version, cancels incomplete old assignments and creates retraining assignments when the revision is marked `RETRAIN`.

Legacy `REFERENCE_ONLY` and `CONTROLLED_COPY` mappings do not create read-and-understand assignments. They are excluded from the SOP-only curriculum workspace. Physical controlled copies are tracked separately by copy number, department and location.

The current role-curriculum workspace intentionally shows SOPs only. Forms remain controlled documents linked visually to their parent SOP and are not duplicated as reading requirements.

## Email notification delivery

The API worker evaluates notifications once per minute when email alerts are enabled. It consolidates multiple new assignments or overdue items into one operator email, records each delivery attempt, retries failures with bounded backoff, and sends a below-threshold message only when the operator crosses from compliant to below the configured threshold. A manual run control supports configuration verification and controlled recovery.

SMTP host, sender, security mode, account and overdue frequency are controlled system settings. The SMTP password is encrypted with a key derived from the installation secret; it is never returned through the API or included in audit before/after values. Assignment and compliance notification state prevents duplicate messages while retaining recurring overdue reminders.

## Training status presentation

| User-facing label | System representation |
|---|---|
| Reading required | Current assignment is assigned and within its due date |
| Read and acknowledged | Current or historical assignment has an attributable acknowledgement |
| Reading overdue | Current assignment remains incomplete after its due date |
| No assignment | No assignment exists for the current effective version and operator |
| Closed — superseded before completion | An incomplete historical assignment was closed when its version was superseded |
| Waived | An authorised person waived the assignment with a recorded reason |

The interface uses these plain-language labels throughout the live matrix and training history. Historical assignment state and acknowledgement evidence remain stored independently of display wording.

## Core entities

- `SecurityRole`, `Permission`, `RolePermission`, `User`, `AuthSession`
- `JobRole`, `UserJobRole`
- `DocumentFamily`, `DocumentVersion`, `VersionSignature`
- `SourceScanRun`, `SourceInventoryFile`
- `RoleDocumentRequirement`, `TrainingAssignment`, `AssignmentSource`, `TrainingAcknowledgement`
- `ControlledCopyIssue`
- `AssignmentNotificationState`, `ComplianceNotificationState`, `EmailNotificationDelivery`
- `AuditEvent`, `SystemSetting`, `BackupRun`

## Trust boundaries

- Identity and permission checks execute in the API for every protected operation.
- Operator clients never receive the shared-folder source path unless their role has document-control access.
- Original source download requires a separate permission.
- Normal operators can view only released/effective versions.
- The web interface omits print/download controls, adds a user watermark and serves `no-store` responses. Browser controls reduce casual copying but cannot guarantee DRM against screenshots or a compromised workstation.
- Nginx and API add restrictive frame, MIME, referrer, cache and content security headers.

## Technology decisions

| Layer | Choice | Reason |
|---|---|---|
| API | Python, FastAPI, SQLAlchemy | Clear domain services, validation and testability |
| Database | PostgreSQL 16 | Transactions, partial indexes, append-only triggers and robust backup tools |
| Web | React 19, TypeScript, Vite | Responsive operator and administration interface |
| Document view | PDF.js + LibreOffice headless | Native PDF display and disposable DOCX rendition |
| Deployment | Docker Compose + Nginx | Reproducible on-premises server installation |
| Schema | Alembic | Forward-controlled database upgrades |
| Password hashing | Argon2 | Memory-hard credential protection |
