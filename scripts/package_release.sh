#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=${1:-0.1.0}
OUTPUT="$PROJECT_ROOT/eaststone-training-matrix-$VERSION.zip"

cd "$PROJECT_ROOT"
"$PROJECT_ROOT/scripts/test_all.sh"
git archive --format=zip --output="$OUTPUT" --prefix="eaststone-training-matrix-$VERSION/" HEAD
sha256sum "$OUTPUT" > "$OUTPUT.sha256"
echo "Created $OUTPUT and SHA-256 manifest."
