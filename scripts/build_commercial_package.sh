#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE_ROOT="$PROJECT_ROOT/release"
STAGING_ROOT="$RELEASE_ROOT/artifact-staging"
PACKAGE_ROOT="$STAGING_ROOT/Eaststone Training Matrix"
SYSTEM_ROOT="$PACKAGE_ROOT/System"
ZIP_PATH="$RELEASE_ROOT/Eaststone-Training-Matrix-Commercial-Package.zip"
ZIP_SHA_PATH="$ZIP_PATH.sha256"

case "$RELEASE_ROOT" in
  "$PROJECT_ROOT/release") ;;
  *) echo "Refusing to clean an unexpected release path: $RELEASE_ROOT" >&2; exit 1 ;;
esac

for command in git sha256sum zip; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required packaging command not found: $command" >&2
    exit 1
  fi
done

commit_sha=${GITHUB_SHA:-$(git -C "$PROJECT_ROOT" rev-parse HEAD)}
short_sha=${commit_sha:0:7}
base_version=$(sed -n 's/^APP_VERSION=//p' "$PROJECT_ROOT/.env.example" | head -n 1 | tr -d '"')
version=${1:-${base_version:-0.1.0}-$short_sha}
source_ref=${GITHUB_REF_NAME:-$(git -C "$PROJECT_ROOT" branch --show-current)}
build_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

rm -rf "$STAGING_ROOT"
rm -f "$ZIP_PATH" "$ZIP_SHA_PATH"
mkdir -p "$SYSTEM_ROOT" "$PACKAGE_ROOT/CLIENT DEPLOYMENT" "$PACKAGE_ROOT/Documentation"

cp -a "$PROJECT_ROOT/api" "$SYSTEM_ROOT/api"
cp -a "$PROJECT_ROOT/infra" "$SYSTEM_ROOT/infra"
cp -a "$PROJECT_ROOT/web" "$SYSTEM_ROOT/web"
cp -a "$PROJECT_ROOT/windows" "$SYSTEM_ROOT/windows"
cp "$PROJECT_ROOT/APP_VERSION" "$SYSTEM_ROOT/APP_VERSION"

rm -rf \
  "$SYSTEM_ROOT/api/tests" \
  "$SYSTEM_ROOT/api/.pytest_cache" \
  "$SYSTEM_ROOT/api/.ruff_cache" \
  "$SYSTEM_ROOT/web/node_modules" \
  "$SYSTEM_ROOT/web/dist"
find "$SYSTEM_ROOT" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \) -prune -exec rm -rf {} +
find "$SYSTEM_ROOT" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -f \
  "$SYSTEM_ROOT/api/requirements-dev.txt" \
  "$SYSTEM_ROOT/api/pytest.ini" \
  "$SYSTEM_ROOT/api/pyproject.toml" \
  "$SYSTEM_ROOT/api/.dockerignore" \
  "$SYSTEM_ROOT/web/.dockerignore"

copy_server_launcher() {
  local source_name=$1
  local package_name=$2
  sed 's|"windows\\|"System\\windows\\|g' \
    "$PROJECT_ROOT/$source_name" > "$PACKAGE_ROOT/$package_name"
}

copy_server_launcher "INSTALL_WINDOWS.bat" "01 - INSTALL SERVER.bat"
copy_server_launcher "START_WINDOWS.bat" "02 - START SERVER.bat"
copy_server_launcher "STOP_WINDOWS.bat" "03 - STOP SERVER.bat"
copy_server_launcher "STATUS_WINDOWS.bat" "04 - SERVER STATUS.bat"
copy_server_launcher "UPDATE_WINDOWS.bat" "05 - UPDATE SERVER.bat"
copy_server_launcher "CONFIGURE_DOCUMENT_FOLDER_WINDOWS.bat" "06 - CONFIGURE DOCUMENT FOLDER.bat"
copy_server_launcher "RESET_ADMIN_PASSWORD_WINDOWS.bat" "07 - RESET ADMIN PASSWORD.bat"
copy_server_launcher "UNINSTALL_WINDOWS.bat" "UNINSTALL SERVER - KEEP DATA.bat"
copy_server_launcher "COMPLETE_UNINSTALL_DELETE_DATA_WINDOWS.bat" "DANGER - COMPLETE UNINSTALL DELETE DATABASE.bat"

sed 's|"windows\\client_setup.ps1"|"client_setup.ps1"|g' \
  "$PROJECT_ROOT/CLIENT_SETUP_WINDOWS.bat" \
  > "$PACKAGE_ROOT/CLIENT DEPLOYMENT/01 - INSTALL CLIENT.bat"
cp "$PROJECT_ROOT/windows/client_setup.ps1" "$PACKAGE_ROOT/CLIENT DEPLOYMENT/client_setup.ps1"

cp "$PROJECT_ROOT"/docs/*.md "$PACKAGE_ROOT/Documentation/"
cp "$PROJECT_ROOT/README.md" "$PACKAGE_ROOT/Documentation/PROJECT README.md"
cp "$PROJECT_ROOT/SECURITY.md" "$PACKAGE_ROOT/Documentation/SECURITY POLICY.md"

cat > "$PACKAGE_ROOT/00 - START HERE - INSTALLATION GUIDE.txt" <<'EOF'
EASTSTONE TRAINING MATRIX - COMMERCIAL PACKAGE

NEW SERVER INSTALLATION
1. Extract this GitHub artifact once onto the Windows server.
2. Confirm Docker with Linux-container support is installed and running.
3. Right-click "01 - INSTALL SERVER.bat" and select Run as administrator.
4. Paste or select Eaststone's top-level approved-document root (UNC paths are supported) and a separate database-backup folder.
5. For UNC shares, enter a dedicated DOMAIN\\username or username@domain service account when Windows prompts. It needs read access to approved documents and write access to backups.
6. The installer creates Docker-managed SMB 3.0 volumes, then verifies it can read every nested PDF/DOCX and write to the backup folder before proceeding.
7. Record the generated installation report and one-time administrator credentials.
8. Sign in, change the initial password, open Source discovery and run the first recursive scan.
9. Correct the suggested metadata and complete the signed approved-baseline import before configuring role curricula.
10. Set the approved compliance/session limits in System. If email alerts are required, add operator email addresses and configure/test the approved SMTP account in Notification settings before enabling delivery.

SAFE RETRY
If an image download or first build fails, correct Docker Desktop DNS/proxy access,
rerun this installer, and type RESUME INSTALLATION. Existing generated secrets and
database state are retained. Progress is also written to INSTALLATION_LOG.txt.

CLIENT DEPLOYMENT
The server installer automatically places server.crt and client-config.json in the
"CLIENT DEPLOYMENT" folder. Copy that prepared folder to each authorised workstation,
then run "01 - INSTALL CLIENT.bat" as administrator. No server-name or port entry is required.

UPDATES
Extract the new approved artifact and run "05 - UPDATE SERVER.bat" as administrator.
The updater creates a pre-update database backup and preserves the database volume,
configuration, TLS keys, controlled-document folder and external backup folder.

IMPORTANT
- No controlled PDF/DOCX files, production database, credentials or TLS keys are in this package.
- Application backups do not copy the external controlled-document folder.
- Read Documentation\INSTALLATION.md and SECURITY_AND_VALIDATION.md before regulated use.
- The destructive complete-uninstall tool requires two explicit confirmations.
- Mapping a folder does not automatically register documents; use Source discovery after login.
EOF

cat > "$PACKAGE_ROOT/CLIENT DEPLOYMENT/README.txt" <<'EOF'
EASTSTONE TRAINING MATRIX - CLIENT DEPLOYMENT

1. Run the server installation/update from the extracted package first. It automatically writes the approved server.crt and client-config.json into this folder.
2. Copy this prepared CLIENT DEPLOYMENT folder to the authorised workstation.
3. Run "01 - INSTALL CLIENT.bat" as administrator.
4. No server name or HTTPS port entry is required; both are loaded from client-config.json.
5. Verify the displayed certificate fingerprint against the server installation report.

Never distribute server.key, .env, database dumps or one-time administrator credentials.
EOF

cat > "$PACKAGE_ROOT/PACKAGE_INFORMATION.txt" <<EOF
Application: Eaststone Training Matrix
Package version: $version
Source reference: $source_ref
Source commit: $commit_sha
Built at UTC: $build_time

This package was created by the validated GitHub commercial-package workflow.
It contains application and installation files only; it contains no controlled documents or production data.
EOF

(
  cd "$PACKAGE_ROOT"
  find . -type f ! -name 'PACKAGE_MANIFEST_SHA256.txt' -print0 \
    | sort -z \
    | xargs -0 sha256sum > PACKAGE_MANIFEST_SHA256.txt
)

mkdir -p "$RELEASE_ROOT"
(
  cd "$STAGING_ROOT"
  zip -q -r -9 "$ZIP_PATH" "Eaststone Training Matrix"
)
sha256sum "$ZIP_PATH" > "$ZIP_SHA_PATH"

echo "Commercial package folder: $PACKAGE_ROOT"
echo "Commercial package ZIP:    $ZIP_PATH"
echo "ZIP checksum:              $ZIP_SHA_PATH"
