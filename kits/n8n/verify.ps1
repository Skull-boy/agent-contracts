#!/usr/bin/env pwsh
# Verify the n8n adoption kit against its pinned reference target.
# Read-only: no network, no secrets, no elevation. Idempotent.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    try {
        $version = & scyvera --version
    } catch {
        [Console]::Error.WriteLine("verify.ps1: cannot run scyvera: $($_.Exception.Message)")
        exit 2
    }
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera --version exited $LASTEXITCODE")
        exit 2
    }
    Write-Output "verify.ps1: $version"

    & scyvera check "implementations/n8n/competitor-feature-parity-watcher" --tier 1
    $code = $LASTEXITCODE

    Write-Output "verify.ps1: expected: PASS, 0 tier-1 findings (exit 0)"
    if ($code -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera check exited $code")
        exit $code
    }

    Write-Output "verify.ps1: n8n kit verified (exit 0)"
    exit 0
} finally {
    Pop-Location
}
