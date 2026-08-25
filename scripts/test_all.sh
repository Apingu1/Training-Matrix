#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"

.venv/bin/ruff format --check api
.venv/bin/ruff check api
.venv/bin/pytest -q api/tests
.venv/bin/pip-audit -r api/requirements.txt
(cd web && npm audit --omit=dev && npm run build)
bash -n run_stack.sh scripts/*.sh

echo "All Eaststone Training Matrix checks passed."
