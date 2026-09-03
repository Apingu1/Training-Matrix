# Installation and server operation

## Supported deployment

The supplied production deployment is Docker Compose on an on-premises server. Windows scripts assume Docker Engine/Docker Desktop with Linux containers, PowerShell 5.1+ and an administrator account. For Windows Server, use an organisation-supported Linux-container engine; do not rely on an interactive desktop session for a production service.

Production qualification should pin an approved release commit/image set and record host OS, Docker and browser versions.

## Before installation

1. Confirm a static server name, time synchronisation and Eaststone backup/patch ownership.
2. Confirm the existing controlled-document share can be read by the Docker service account. The application mount is read-only.
3. Create a separate writable backup folder on protected storage.
   If either selected folder is a UNC share, prepare a dedicated least-privilege domain/service account. It needs read access to approved documents and read/write access to backups. Docker will require this credential to establish SMB mounts.
4. Confirm HTTPS port `8090` (or choose another) is allowed only from the authorised network.
5. Decide whether to use Eaststone PKI. The installer creates a 825-day self-signed certificate for initial deployment; a CA-issued server certificate is preferable.
6. Approve the configuration and validation protocol before regulated data entry.

## Windows installation

1. Download the successful workflow artifact named `Eaststone-Training-Matrix-Commercial-Package`, record the workflow identity/digest, then extract it once on the server.
2. Read `00 - START HERE - INSTALLATION GUIDE.txt`, then right-click `01 - INSTALL SERVER.bat` and choose **Run as administrator**.
3. Enter or select the existing controlled-document **root** folder and a separate backup folder. The root may contain hundreds of nested folders; every PDF/DOCX beneath it is discovered recursively.
4. Enter the HTTPS port or accept `8090`.
5. Wait for database migration, image build and health checks.
6. Retain `C:\ProgramData\Eaststone\TrainingMatrix\INSTALLATION_REPORT.txt` as IQ evidence.
7. Retrieve the one-time credentials from `INITIAL_ADMIN_CREDENTIALS.txt`, sign in, change the password immediately and securely delete that credentials file.
8. The successful server installation copies `server.crt` and a generated `client-config.json` into the release's `CLIENT DEPLOYMENT` folder. Copy that prepared folder through an authenticated administrative channel to each authorised workstation, then run `01 - INSTALL CLIENT.bat` as administrator. The client reads the server name and port automatically. Verify the displayed fingerprint against the installation report.
9. Complete the qualification and release checks in [Security and validation](SECURITY_AND_VALIDATION.md).

The Windows launchers use `pushd` before invoking PowerShell, so an extracted package may be run directly from an authorised mapped drive or UNC share. The command window remains open after server or client installation and displays an explicit success or failure result.

### Mapped drives and UNC paths

Windows often hides drive mappings such as `N:` from a program launched with **Run as administrator**. The installer and folder-configuration tool therefore accept a typed path before opening the browser:

- paste `N:\Approved Documents` if that mapping is visible to the elevated account; the installer attempts to resolve it to its UNC target;
- preferably paste the permanent UNC path, for example `\\fileserver\quality\Approved Documents`;
- select the top-level Approved Documents folder, not each SOP subfolder.

Before creating or changing the installation, the tool starts a disposable Docker validation container and proves that Docker can read the selected root recursively. It reports the number of PDF/DOCX files found without copying them. It separately proves that the backup folder is writable. If either test fails, no folder change is committed.

For UNC locations, the installer creates Docker-managed SMB 3.0 volumes instead of attempting an unsupported Linux-container bind mount of the Windows UNC path. A Windows credential prompt appears once per file server when the volume is first created. Use a dedicated least-privilege account in `DOMAIN\username` or `username@domain` form. The credential is not placed in `.env`; Docker administrators can inspect Docker volume configuration, so server/Docker administrative access must remain restricted and the service-account password must be rotated through a controlled reinstallation of the affected SMB volumes.

The SMB volume is mounted at the share boundary and Docker's volume-subpath restriction exposes only the exact selected controlled-document or backup subfolder to the relevant container. This prevents a deep UNC selection from silently widening to the entire network share.

### First installation and safe resume

The first build can take several minutes. Compose runs detached and the installer prints a status update every 15 seconds while waiting, so a stream of container logs is not the installation itself. Detailed output is retained in `INSTALLATION_LOG.txt`.

If Docker Hub DNS/proxy access interrupts the first image download, the installer retries three times and preserves the generated secrets, paths and partial database. Correct Docker Desktop connectivity (a manual `docker pull alpine/openssl:latest` is acceptable), rerun the same installer and enter exactly `RESUME INSTALLATION`. Do not delete `.env` merely to retry.

The installer applies the Windows ACL needed for the Linux nginx container to read `server.key`. `START_WINDOWS.bat` and `UPDATE_WINDOWS.bat` reapply that ACL before starting, which also repairs an installation affected by the earlier nginx `Permission denied` restart loop.

Installed application files live under `C:\ProgramData\Eaststone\TrainingMatrix`. PostgreSQL and runtime data use named Docker volumes; backups and controlled documents stay in the selected host folders.

## First controlled-source baseline

Folder configuration makes documents available read-only; it intentionally does not create master-list records automatically.

1. Sign in with a role that has both document management and approval permissions.
2. Open **Source discovery** and choose **Scan source now**.
3. Review the Registered, Unregistered, Duplicate, Changed, Missing, Unsupported and Scan error views.
4. Correct the detected document number, version, title, type, owner department and dates.
5. Choose **Select likely current versions**. The helper selects the highest inferred version per document number and leaves older or ambiguous files for manual review.
6. Review the exact list, enter the controlled reason and your password, then enter the displayed confirmation phrase.

The API re-checks that every selected path and hash still matches the latest inventory, then hashes each file again before registration. Each released baseline version receives an electronic signature and individual audit event; the batch receives a final count and SHA-256 digest. Subsequent scheduled scans identify additions, external changes and missing files. The scan interval is configurable in **System** (5–1440 minutes; default 60).

## Existing Eaststone certificate

To replace the generated certificate, place PEM files at:

- `C:\ProgramData\Eaststone\TrainingMatrix\tls\server.crt`
- `C:\ProgramData\Eaststone\TrainingMatrix\tls\server.key`

Include the server DNS name in the certificate SAN, then run `START_WINDOWS.bat`. The start tool restricts full control to Administrators/SYSTEM and grants the local built-in Users group read-only access required by Docker Desktop's Linux bind mount. Interactive logon to the server must therefore be restricted to authorised administrators. Certificate replacement and expiry monitoring are controlled server-administration activities.

## Routine server tools

| Tool | Behaviour |
|---|---|
| `STATUS_WINDOWS.bat` | Shows containers and database health |
| `START_WINDOWS.bat` | Starts/reconciles services without changing data |
| `STOP_WINDOWS.bat` | Stops services and retains volumes/files |
| `CONFIGURE_DOCUMENT_FOLDER_WINDOWS.bat` | Selects a new read-only source mount and recreates the API |
| `RESET_ADMIN_PASSWORD_WINDOWS.bat` | Resets one user, forces a change and revokes existing sessions |
| `UPDATE_WINDOWS.bat` | Creates pre-update DB backup, archives old app files, migrates and health-checks |
| `UNINSTALL_WINDOWS.bat` | Removes containers/network but retains all data and installation files |
| `COMPLETE_UNINSTALL_DELETE_DATA_WINDOWS.bat` | Two-stage destructive deletion of DB volumes and installed files; external documents/backups remain |

## Controlled update

Run `UPDATE_WINDOWS.bat` from an extracted, approved **new** release. It will:

1. archive the currently installed application files;
2. create a `PRE_UPDATE` database backup;
3. stop application services;
4. copy the new release while preserving `.env`, TLS keys, database volume and external folders;
5. run forward migrations and start services;
6. wait for health and write an operations-log entry.

Do not attempt an ad-hoc downgrade after a schema migration. Use the approved recovery protocol and the pre-update backup if rollback is required.

## Linux/manual deployment

Copy `.env.example` to `.env`, replace every placeholder with generated secrets and absolute host paths, provide `tls/server.crt` and `tls/server.key`, then:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
docker compose --env-file .env -f infra/docker-compose.yml ps
curl http://127.0.0.1:18090/health
```

Protect `.env` and the TLS private key with operating-system permissions. The external user URL is `https://SERVER:8090`; the HTTP health port binds to localhost only.

## Shared-folder rules

- Configure the top-level controlled-document root, not an individual SOP folder.
- Discovery is recursive; documents may remain inside per-SOP subfolders.
- Supported sources are `.pdf` and `.docx`.
- Other file types are inventoried as **Unsupported** for review and are never registered by the baseline tool.
- Keep file paths stable after a version is registered.
- Controllers may update a draft in the share and use **Refresh draft file** before submission.
- Never replace an in-review, approved, released or superseded file in place. Register a new revision instead.
- If the source folder is moved, use the configuration script and then verify all current source hashes in the application.
