# Security and validation plan

## Implemented controls

- Argon2 password hashing and minimum complexity policy.
- Forced password change for temporary/reset credentials.
- Database-backed, revocable sessions with configurable inactivity expiry.
- Failed-login counting, timed lock and audited successes/failures.
- Server-side permission checks on every protected API route.
- Dynamic least-privilege roles; built-in roles cannot be retired; last-admin guard.
- Session revocation after deactivation, role change, reset and password change.
- TLS 1.2/1.3 proxy configuration and restrictive browser/API headers.
- Root-constrained read-only shared-folder access and extension allowlist.
- Recursive source inventory with symlink exclusion, bounded file count, persistent classification and exact hashes.
- Signed baseline import requiring combined management/approval authority, password re-authentication, an exact confirmation phrase, latest-inventory match and a final file re-hash.
- Exact SHA-256 binding through revision lifecycle, signature, view and acknowledgement.
- Independent document approval and password re-authentication for approval/release/obsolescence.
- Append-only database triggers for audit events, acknowledgements and signatures.
- Reason-required administrative and quality actions.
- Non-destructive staged restore and pre-change backups.

## Residual risks and procedural controls

| Risk | Required control |
|---|---|
| Screenshot/photograph of a view-only document | Workstation policy, access control, watermarking and operator SOP; browser UI is not DRM |
| Shared-folder admin changes a released file | Restrict share writes, monitor/backup it; application hash mismatch fails closed |
| Self-signed certificate distribution | Verify fingerprint out of band or replace with Eaststone CA certificate |
| Local server administrator access | Named admin accounts, Windows/Docker audit, least privilege and periodic review |
| Docker Desktop requires read access to the TLS key bind mount | Full control remains Administrators/SYSTEM; built-in Users receives read only; prohibit unauthorised interactive server logon |
| Loss of both DB and document share | Separate failure domains, monitored backups and recovery tests |
| Incorrect curriculum configuration | QA-approved role/document review and sampled matrix verification |
| User attests without comprehension | Training SOP, manager oversight and practical qualification where risk requires it |

## Validation classification

Eaststone Quality should perform a documented risk assessment and determine the applicable lifecycle (for example GAMP 5 and relevant electronic-record/signature expectations). The software should not be described as validated until approved evidence is complete.

## Suggested IQ

- Verify approved commit/release hash and package SHA-256.
- Record server OS, Docker, database image and browser versions.
- Confirm installed paths, named volumes, read-only document mount and writable backup mount.
- Confirm server time/timezone and synchronisation.
- Confirm TLS name, chain/fingerprint, allowed network path and firewall rule.
- Confirm migration head, container health and installation report.
- Confirm UNC/mapped source resolution, recursive PDF/DOCX preflight count, backup write preflight and nginx TLS-key readability.
- Confirm generated credentials are changed and temporary credentials file removed.

## Suggested OQ

- Authentication, lockout, timeout, reset and session-revocation challenges.
- Permission matrix positive/negative tests for all built-in roles.
- Create draft; refresh source; submit; reject creator self-approval; independently approve/release.
- Recursively scan a representative nested source; verify every classification, correct inferred metadata and complete a signed baseline batch.
- Add, alter and remove representative source files; verify Unregistered, Changed and Missing detection and audit evidence.
- Scheduled effective release and automatic supersession/retraining.
- Tamper with a registered source and verify blocked transition/view/acknowledgement plus audit.
- Configure role curriculum and current/future-dated users; verify de-duplication.
- View and sign as operator; verify exact version/hash/history and matrix status.
- Verify plain-language current and historical training labels against the underlying assignment, document-version and acknowledgement records.
- Issue/return/destroy controlled copies.
- Search/export audit; attempt DB update/delete of append-only records.
- Automatic/manual backup, checksum/catalogue verification and staged restore.
- Stop/start/update/non-destructive uninstall recovery tests.

## Suggested PQ/UAT

- QA-approved representative SOPs/forms from the production share.
- Representative production roles and operators.
- Realistic new starter, role change, revision/retraining and leaver scenarios.
- Review-cycle and overdue reporting.
- Performance with expected document/matrix size and concurrent users.
- Disaster-recovery exercise against agreed RPO/RTO.

## Automated evidence in this repository

The test suite covers password policy, forced initial password change, role/user setup, recursive source discovery/classification, signed baseline registration, subsequent change/missing detection, curriculum creation/reinstatement, independent approval/release, auto-assignment, controlled-copy lifecycle, operator view/signature, matrix completion, tamper blocking/audit and path traversal rejection. CI also enforces Python formatting/lint, dependency audits, a TypeScript production build, PowerShell parsing and a Windows installer/Compose argument contract.

Automated tests support but do not replace approved validation protocols, traced evidence and authorised production release.

## Release checklist

- [ ] Requirements and risk assessment approved
- [ ] Code review and CI green on immutable commit
- [ ] Dependency/security review completed
- [ ] IQ/OQ/PQ or approved equivalent passed
- [ ] Shared-folder permissions and backup verified
- [ ] Database backup and restore exercise passed
- [ ] TLS certificate approved and expiry owner assigned
- [ ] Security roles/curricula reviewed by QA
- [ ] Operating, incident, access and backup SOPs effective
- [ ] Training completed for administrators/controllers/operators
- [ ] Production release authorised with rollback plan
