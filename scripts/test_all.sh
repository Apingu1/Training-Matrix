#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"

.venv/bin/ruff format --check api
.venv/bin/ruff check api
.venv/bin/pytest -q api/tests
(cd web && npm run build)

echo "All Eaststone Training Matrix checks passed."
