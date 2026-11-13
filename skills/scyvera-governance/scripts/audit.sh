#!/usr/bin/env sh
# Run `scyvera audit` with an explicit exit-code capture.
# Read-only: no network, no secrets, no elevation.
set -u

path=${1:-.}
fail_under=${2:-0}

if ! command -v scyvera >/dev/null 2>&1; then
    echo "audit.sh: scyvera is not on PATH" >&2
    exit 2
fi

scyvera audit "$path" --fail-under "$fail_under"
code=$?
echo "audit.sh: scyvera audit exited $code"
exit "$code"
