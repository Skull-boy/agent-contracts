#!/usr/bin/env bash
# Negative fixture for AU-SH-001: single-file delete, no recursion or force.
set -euo pipefail

rm -f "./tmp/build.log"
