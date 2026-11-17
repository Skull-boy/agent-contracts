#!/usr/bin/env pwsh
# Verify the Google ADK adoption kit against its read-only contract fixture.
# Read-only: no network, no secrets, no elevation, no installs. Idempotent.
#
# The kit lives at docs/kits/google-adk/, one level deeper than the shipped
# kits/ targets, so the repository root is three levels up.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
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

    $kit = "docs/kits/google-adk"
    $template = "$kit/contract.template.yaml"

    & scyvera validate $template
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera validate exited $code")
        exit $code
    }

    & scyvera lint $template
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera lint exited $code")
        exit $code
    }

    & scyvera check $template --tier 0
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera check exited $code")
        exit $code
    }

    & scyvera audit $kit
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("verify.ps1: scyvera audit exited $code")
        exit $code
    }

    Write-Output "verify.ps1: expected: PASS tier 0, 0 schema errors, 0 semantic warnings, audit 100/100 (exit 0)"
    Write-Output "verify.ps1: tier 1 is not claimed: no Google ADK adapter exists yet"
    Write-Output "verify.ps1: google-adk kit verified (exit 0)"
    exit 0
} finally {
    Pop-Location
}
