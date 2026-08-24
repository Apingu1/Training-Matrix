#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ENV_FILE="$PROJECT_ROOT/.env"
COMPOSE_FILE="$PROJECT_ROOT/infra/docker-compose.yml"
DEV_ROOT="$PROJECT_ROOT/runtime/development"
DOCUMENTS_PATH="$DEV_ROOT/controlled-documents"
BACKUPS_PATH="$DEV_ROOT/backups"
TLS_PATH="$DEV_ROOT/tls"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

read_env_value() {
  local key=$1
  local value
  value=$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)
  value=${value#\"}
  value=${value%\"}
  printf '%s' "$value"
}

require_command docker
require_command curl
docker version >/dev/null
docker compose version >/dev/null

created_environment=false
if [[ ! -f "$ENV_FILE" ]]; then
  require_command openssl
  mkdir -p "$DOCUMENTS_PATH" "$BACKUPS_PATH" "$TLS_PATH"

  database_secret=$(openssl rand -hex 32)
  jwt_secret=$(openssl rand -hex 48)
  initial_admin_password="Tm!$(openssl rand -hex 12)9aZ"
  app_port=${TRAINING_MATRIX_HTTPS_PORT:-8090}
  preview_port=${TRAINING_MATRIX_PREVIEW_PORT:-18090}

  umask 077
  printf '%s\n' \
    'APP_NAME="Eaststone Training Matrix"' \
    'APP_VERSION="0.1.0"' \
    'APP_ENV="development"' \
    "APP_PORT=\"$app_port\"" \
    "APP_HEALTH_PORT=\"$preview_port\"" \
    'TZ="Europe/London"' \
    'POSTGRES_DB="training_matrix"' \
    'POSTGRES_USER="training_matrix"' \
    "POSTGRES_PASSWORD=\"$database_secret\"" \
    "DATABASE_URL=\"postgresql+psycopg://training_matrix:$database_secret@db:5432/training_matrix\"" \
    "JWT_SECRET=\"$jwt_secret\"" \
    'JWT_EXPIRES_MINUTES="480"' \
    'SESSION_IDLE_MINUTES="15"' \
    'LOGIN_MAX_FAILURES="5"' \
    'LOGIN_LOCK_MINUTES="15"' \
    'INITIAL_ADMIN_USERNAME="admin"' \
    "INITIAL_ADMIN_PASSWORD=\"$initial_admin_password\"" \
    "DOCUMENTS_HOST_PATH=\"$DOCUMENTS_PATH\"" \
    "BACKUP_HOST_PATH=\"$BACKUPS_PATH\"" \
    "TLS_CERT_HOST_PATH=\"$TLS_PATH\"" \
    'DOCUMENT_ROOT="/controlled-documents"' \
    'BACKUP_ROOT="/backups"' \
    'DOCUMENT_CACHE_ROOT="/document-cache"' \
    'RUNTIME_ROOT="/runtime"' \
    'BACKUP_TIME="02:30"' \
    'BACKUP_TIMEZONE="Europe/London"' \
    'BACKUP_RETENTION_DAYS="30"' \
    > "$ENV_FILE"
  created_environment=true
  echo "Created a private development environment at .env."
else
  echo "Using the existing .env; database volumes and application data will be preserved."
fi

documents_host_path=$(read_env_value DOCUMENTS_HOST_PATH)
backups_host_path=$(read_env_value BACKUP_HOST_PATH)
tls_host_path=$(read_env_value TLS_CERT_HOST_PATH)
app_port=$(read_env_value APP_PORT)
preview_port=$(read_env_value APP_HEALTH_PORT)
admin_username=$(read_env_value INITIAL_ADMIN_USERNAME)
initial_admin_password=$(read_env_value INITIAL_ADMIN_PASSWORD)

if [[ -z "$documents_host_path" || -z "$backups_host_path" || -z "$tls_host_path" ]]; then
  echo "DOCUMENTS_HOST_PATH, BACKUP_HOST_PATH and TLS_CERT_HOST_PATH must be configured in .env." >&2
  exit 1
fi

mkdir -p "$documents_host_path" "$backups_host_path" "$tls_host_path"

if [[ ! -s "$tls_host_path/server.crt" || ! -s "$tls_host_path/server.key" ]]; then
  require_command openssl
  openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 825 \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -keyout "$tls_host_path/server.key" \
    -out "$tls_host_path/server.crt" >/dev/null 2>&1
  chmod 600 "$tls_host_path/server.key"
  chmod 644 "$tls_host_path/server.crt"
  echo "Created a development TLS certificate."
fi

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${compose[@]}" up -d --build

echo "Waiting for Eaststone Training Matrix to become healthy..."
healthy=false
for _ in {1..90}; do
  if curl --fail --silent --show-error "http://127.0.0.1:${preview_port}/health" >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != true ]]; then
  echo "The stack did not become healthy. Recent service output:" >&2
  "${compose[@]}" ps >&2
  "${compose[@]}" logs --tail 120 api web db-init >&2
  exit 1
fi

echo
echo "Eaststone Training Matrix is running."
if [[ -n "${CODESPACE_NAME:-}" ]]; then
  forwarding_domain=${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}
  echo "Codespace preview: https://${CODESPACE_NAME}-${preview_port}.${forwarding_domain}"
  echo "If it does not open automatically, use the Ports panel and open port ${preview_port}."
else
  echo "Local preview:     http://localhost:${preview_port}"
  echo "TLS preview:       https://localhost:${app_port}"
fi
echo "Document folder:   $documents_host_path"
echo "Backup folder:     $backups_host_path"
echo "Username:          ${admin_username:-admin}"
if [[ "$created_environment" == true ]]; then
  echo "Initial password:  $initial_admin_password"
  echo "You will be required to change this password at first login."
else
  echo "Use the password already configured or previously changed for this dataset."
fi
echo
echo "Run this script again after code changes. It never removes Docker volumes."
