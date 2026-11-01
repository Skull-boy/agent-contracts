#!/usr/bin/env bash
# Positive fixture: AU-GIT-001 (force push).
set -euo pipefail

git push --force origin main
