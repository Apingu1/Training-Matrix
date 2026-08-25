#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/test_all.sh"
if [ "$#" -gt 0 ]; then
  "$PROJECT_ROOT/scripts/build_commercial_package.sh" "$1"
else
  "$PROJECT_ROOT/scripts/build_commercial_package.sh"
fi
