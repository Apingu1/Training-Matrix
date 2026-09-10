# User requirements and acceptance criteria

## Scope

The system shall manage Eaststone's controlled-document master list and role-derived read-and-understand training without storing authoritative document content in the application.

## Functional requirements

| ID | Requirement | Acceptance evidence |
|---|---|---|
| URS-001 | Configure one shared server folder containing PDF/DOCX controlled sources | System page reports configured path availability/readability; browse is root constrained |
| URS-002 | Maintain document number, title, type, owner, review interval and active state | Create/update API and Document Control UI; audit before/after/reason |
| URS-003 | Maintain immutable revision records and one current effective version per family | Unique constraints, lifecycle test and version history UI |
| URS-004 | Prevent uncontrolled file replacement | Hash verified at transition, view and acknowledgement; mismatch blocks and audits |
| URS-005 | Provide view-only normal-operator access | Operator role has view permission only; viewer has no source download route/control |
| URS-006 | Require independent approval and signed release | Creator approval blocked; approval/release password re-auth and immutable signature |
| URS-007 | Define documents required for each job role | Curriculum UI/API with active requirement and due days |
| URS-008 | Assign current/revised documents to active users in required roles | Release, requirement, immediate and effective-dated role reconciliation services |
| URS-009 | Record read-and-understood confirmation | Verified prior view, password re-auth, exact hash and append-only acknowledgement |
| URS-010 | Show current and historical operator compliance | My Training, role matrix, team summary and user history |
| URS-011 | Preserve superseded read/not-read history | Old assignments close; completed acknowledgement is retained |
| URS-012 | Support individual assignments and authorised waivers | Permissioned endpoints/UI with reason and audit |
| URS-013 | Track physical controlled-copy distribution | Issue/return/destroy register per released version |
| URS-014 | Provide permissioned user/security-role administration | Dynamic permission matrix and server enforcement |
| URS-015 | Provide an append-only searchable audit trail | Database triggers, filters and CSV/PDF export |
| URS-016 | Provide automatic/manual backup, verification and safe restore | Dump, SHA manifest, retention, pre-restore backup and staged dataset |
| URS-017 | Install and operate on an Eaststone server | Docker Compose and Windows administration scripts |
| URS-018 | Do not import the current spreadsheet in this release | No migration command or seeded operational data is included |
| URS-019 | Discover files beneath the configured root recursively without copying them | Nested PDF/DOCX integration test and Docker read-only preflight |
| URS-020 | Distinguish registered, unregistered, duplicate, changed, missing, unsupported and scan-error sources | Persistent inventory classifications and Source discovery filters |
| URS-021 | Suggest document number/version metadata and allow controlled correction | Filename/folder inference plus editable baseline review |
| URS-022 | Bulk-register only the reviewed approved current baseline | Highest-version selection helper; permission, password, confirmation, inventory and re-hash checks |
| URS-023 | Record complete baseline provenance | Per-version electronic signature/audit plus batch count and digest |
| URS-024 | Detect later additions and external source changes | Configurable automatic scan and manual rescan; changed/missing classifications |
| URS-025 | Maintain curricula efficiently at expected scale | SOP-only document rows × active-role columns with checkboxes, one reason and one save action |
| URS-026 | Measure active training compliance against an administrator-set threshold | Configurable percentage, operator scores, average score and below-threshold count/alert tab |
| URS-027 | Filter the live matrix by role, operator and multiple training statuses | Role/operator selectors and multi-select Reading required, Read and acknowledged, Reading overdue and No assignment filters |
| URS-028 | End inactive and overlong authenticated sessions | Configurable idle and absolute limits enforced by browser activity tracking and the server session record |
| URS-029 | Show SOP/form relationships without assigning forms as reading requirements | Green SOP parents, blue indented forms and linked parent/child details |
| URS-030 | Notify users of training obligations by email | Configurable SMTP, consolidated new-assignment messages, recurring overdue reminders and below-threshold transition alerts |
| URS-031 | Retain notification accountability without exposing SMTP credentials | Permissioned settings, encrypted password, masked API output, delivery register, retries and audit events |

## Permission roles supplied

- `ADMIN`: technical administration and all permissions.
- `QA_APPROVER`: independent approval/release, training oversight and audit.
- `DOCUMENT_CONTROLLER`: master list, revisions, review, curricula and controlled copies.
- `MANAGER_TRAINER`: team compliance, assignments and waivers. The name denotes responsibility; there is no `t` cell marker.
- `OPERATOR`: released document viewing and own acknowledgement only.
- `AUDITOR`: read-only document, compliance and audit access.

Administrators may create additional roles and permission bundles. Built-in roles remain available as safe recovery baselines.

## Out of scope for the initial build

- Migration of spreadsheet records or legacy read/training states. The controlled-source baseline imports approved files and metadata only.
- Authoring/editing PDF or DOCX content in the web application.
- Replacing the shared-folder backup or access-control process.
- Qualification sign-off, practical observation or exam scoring beyond read-and-understand acknowledgement.
- External identity provider integration and native mobile apps.

These are potential controlled enhancements and require separate requirements, risk assessment and validation.
