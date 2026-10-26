[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Dataset,
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$Trigger,
    [string]$Python = 'python',
    [string]$OutputDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'training-bundles'),
    [string]$Recipe,
    [string]$Runpodctl = "$HOME\Downloads\runpodctl.exe",
    [switch]$PrepareOnly,
    [switch]$NewTransfer
)
$ErrorActionPreference = 'Stop'
$buildArgs = @((Join-Path $PSScriptRoot 'build_bundle.py'), '--dataset', $Dataset,
    '--name', $Name, '--trigger', $Trigger, '--output-dir', $OutputDir)
if ($Recipe) { $buildArgs += @('--recipe', $Recipe) }
& $Python @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'Bundle validation failed; no sender was started.' }
$report = Join-Path $OutputDir "moss_${Name}_validation.json"
& (Join-Path $PSScriptRoot 'send_bundle.ps1') -ValidationReport $report -Runpodctl $Runpodctl -CheckOnly:$PrepareOnly -NewTransfer:$NewTransfer
