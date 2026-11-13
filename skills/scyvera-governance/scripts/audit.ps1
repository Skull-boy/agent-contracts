#!/usr/bin/env pwsh
# Run `scyvera audit` with an explicit exit-code capture.
# Read-only: no network, no secrets, no elevation.
param(
    [string]$Path = ".",
    [int]$FailUnder = 0
)

$ErrorActionPreference = "Stop"

try {
    & scyvera audit $Path --fail-under $FailUnder
} catch {
    [Console]::Error.WriteLine("audit.ps1: cannot run scyvera: $($_.Exception.Message)")
    exit 2
}

$code = $LASTEXITCODE
Write-Output "audit.ps1: scyvera audit exited $code"
exit $code
