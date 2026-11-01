#!/usr/bin/env bash
# Negative fixture for AU-GIT-001: ordinary push, no ref rewriting.
set -euo pipefail

git push origin main
