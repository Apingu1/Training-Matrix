#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=${1:-0.1.0}

cd "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/test_all.sh"
"$PROJECT_ROOT/scripts/build_commercial_package.sh" "$VERSION"
