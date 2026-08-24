# Installation and server operation

## Supported deployment

The supplied production deployment is Docker Compose on an on-premises server. Windows scripts assume Docker Engine/Docker Desktop with Linux containers, PowerShell 5.1+ and an administrator account. For Windows Server, use an organisation-supported Linux-container engine; do not rely on an interactive desktop session for a production service.

Production qualification should pin an approved release commit/image set and record host OS, Docker and browser versions.

## Before installation

1. Confirm a static server name, time synchronisation and Eaststone backup/patch ownership.
2. Confirm the existing controlled-document share can be read by the Docker service account. The application mount is read-only.
3. Create a separate writable backup folder on protected storage.
4. Confirm HTTPS port `8090` (or choose another) is allowed only from the authorised network.
5. Decide whether to use Eaststone PKI. The installer creates a 825-day self-signed certificate for initial deployment; a CA-issued server certificate is preferable.
6. Approve the configuration and validation protocol before regulated data entry.

## Windows installation

1. Download the successful workflow artifact named `Eaststone-Training-Matrix-Commercial-Package`, record the workflow identity/digest, then extract it once on the server.
2. Read `00 - START HERE - INSTALLATION GUIDE.txt`, then right-click `01 - INSTALL SERVER.bat` and choose **Run as administrator**.
3. Select the existing controlled-document folder and a separate backup folder.
4. Enter the HTTPS port or accept `8090`.
5. Wait for database migration, image build and health checks.
6. Retain `C:\ProgramData\Eaststone\TrainingMatrix\INSTALLATION_REPORT.txt` as IQ evidence.
7. Retrieve the one-time credentials from `INITIAL_ADMIN_CREDENTIALS.txt`, sign in, change the password immediately and securely delete that credentials file.
8. Copy `tls\server.crt` through an authenticated administrative channel to each authorised workstation. Place it beside `CLIENT_SETUP_WINDOWS.bat`, then run the client script as administrator with the exact server name. Verify the displayed fingerprint against the installation report.
9. Complete the qualification and release checks in [Security and validation](SECURITY_AND_VALIDATION.md).

Installed application files live under `C:\ProgramData\Eaststone\TrainingMatrix`. PostgreSQL and runtime data use named Docker volumes; backups and controlled documents stay in the selected host folders.

## Existing Eaststone certificate

To replace the generated certificate, place PEM files at:

- `C:\ProgramData\Eaststone\TrainingMatrix\tls\server.crt`
- `C:\ProgramData\Eaststone\TrainingMatrix\tls\server.key`

Restrict the private key to Administrators/SYSTEM, include the server DNS name in the certificate SAN, then run `START_WINDOWS.bat`. Certificate replacement and expiry monitoring are controlled server-administration activities.

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
- Supported sources are `.pdf` and `.docx`.
- Keep file paths stable after a version is registered.
- Controllers may update a draft in the share and use **Refresh draft file** before submission.
- Never replace an in-review, approved, released or superseded file in place. Register a new revision instead.
- If the source folder is moved, use the configuration script and then verify all current source hashes in the application.
