#!/usr/bin/env sh
# Verify the n8n adoption kit against its pinned reference target.
# Read-only: no network, no secrets, no elevation. Idempotent.
set -u

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd) || exit 2
cd "$root" || exit 2

if ! command -v scyvera >/dev/null 2>&1; then
    echo "verify.sh: scyvera is not on PATH" >&2
    exit 2
fi

echo "verify.sh: $(scyvera --version)"
scyvera check implementations/n8n/competitor-feature-parity-watcher --tier 1
code=$?

echo "verify.sh: expected: PASS, 0 tier-1 findings (exit 0)"
if [ "$code" -ne 0 ]; then
    echo "verify.sh: scyvera check exited $code" >&2
    exit "$code"
fi

echo "verify.sh: n8n kit verified (exit 0)"
exit 0
