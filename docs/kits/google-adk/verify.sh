#!/usr/bin/env sh
# Verify the Google ADK adoption kit against its read-only contract fixture.
# Read-only: no network, no secrets, no elevation, no installs. Idempotent.
#
# The kit lives at docs/kits/google-adk/, one level deeper than the shipped
# kits/ targets, so the repository root is three levels up.
set -u

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd) || exit 2
cd "$root" || exit 2

if ! command -v scyvera >/dev/null 2>&1; then
    echo "verify.sh: scyvera is not on PATH" >&2
    exit 2
fi

kit=docs/kits/google-adk
template=$kit/contract.template.yaml

echo "verify.sh: $(scyvera --version)"

scyvera validate "$template"
code=$?
if [ "$code" -ne 0 ]; then
    echo "verify.sh: scyvera validate exited $code" >&2
    exit "$code"
fi

scyvera lint "$template"
code=$?
if [ "$code" -ne 0 ]; then
    echo "verify.sh: scyvera lint exited $code" >&2
    exit "$code"
fi

scyvera check "$template" --tier 0
code=$?
if [ "$code" -ne 0 ]; then
    echo "verify.sh: scyvera check exited $code" >&2
    exit "$code"
fi

scyvera audit "$kit"
code=$?
if [ "$code" -ne 0 ]; then
    echo "verify.sh: scyvera audit exited $code" >&2
    exit "$code"
fi

echo "verify.sh: expected: PASS tier 0, 0 schema errors, 0 semantic warnings, audit 100/100 (exit 0)"
echo "verify.sh: tier 1 is not claimed: no Google ADK adapter exists yet"
echo "verify.sh: google-adk kit verified (exit 0)"
exit 0
