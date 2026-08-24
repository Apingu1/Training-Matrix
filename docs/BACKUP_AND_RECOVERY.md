# Backup and recovery

## What the application backup contains

Each PostgreSQL custom-format backup contains all application metadata and evidence, including users, permissions, document master/version records, file fingerprints, curricula, assignments, acknowledgements, signatures, controlled copies, settings and audit events.

Its adjacent manifest contains SHA-256, size, version, reason and an inventory of external document paths/hashes.

## What it does not contain

PDF/DOCX files in the controlled-document share are **not** copied. DOCX-derived PDFs are disposable cache and are also excluded. Eaststone must maintain a separate protected backup of the shared folder that preserves content, paths and recovery points.

Recovery is complete only when both are available:

- a verified Training Matrix database backup; and
- a matching/restorable shared-folder snapshot whose files satisfy the recorded SHA-256 inventory.

## Schedule and retention

- Default automatic backup: daily at `02:30 Europe/London`.
- Default automatic retention: 30 days.
- Manual and pre-update/pre-restore backups are not removed by automatic retention.
- The backup scheduler uses a process lock and records success/failure in the audit trail.

Backups should be copied by infrastructure tooling to a separate failure domain with restricted access and monitored capacity. Retention must follow Eaststone's approved record-retention policy; the default is only a technical starting point.

## Verification

The **Verify** action recalculates SHA-256 and asks `pg_restore` to read the dump catalogue. Periodically perform a full test restore into an isolated qualification environment; catalogue verification alone does not prove recovery objectives.

## Restore safeguards

1. An administrator enables maintenance mode.
2. The selected dump is verified.
3. The user enters the exact confirmation text and a reason.
4. A current `PRE_RESTORE` backup must complete successfully.
5. The dump restores to a newly named PostgreSQL dataset.
6. Sanity checks count users, documents and audit events.
7. Only then does the application activate the new dataset.
8. The previous dataset remains available for controlled recovery.
9. All sessions should be treated as invalid operationally; sign out/in and confirm scheduler/status after restore.

## Recovery test evidence

Record at minimum: backup filename/hash, shared-folder snapshot identifier, tester, date/time, release version, restore duration, row-count sanity results, sampled document hash/view, sampled acknowledgement/audit history, permissions check, scheduler status, and approval of the outcome.

## Failure scenarios

| Scenario | Response |
|---|---|
| Database unavailable | Stop use, preserve logs/volumes, restore a verified DB backup if authorised |
| Shared folder unavailable | Document views fail closed; restore/remount the share, then verify hashes |
| File hash mismatch | Do not overwrite the DB fingerprint; investigate the shared-folder change and either restore the exact file or create a controlled new revision |
| Failed update | Retain containers/logs, pre-update backup and archived app files; follow approved rollback/recovery |
| Backup folder full/unavailable | Alert owner, restore capacity/path and run/verify a manual backup |
| TLS certificate expired | Replace with approved certificate/key and restart web service; do not bypass warnings in production |
