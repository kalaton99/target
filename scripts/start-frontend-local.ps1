Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $RepoRoot "frontend"

if (-not (Test-Path $FrontendDir)) {
    throw "Frontend directory not found: $FrontendDir"
}

Set-Location $FrontendDir
$env:REACT_APP_BACKEND_URL = "http://127.0.0.1:8000"

Write-Host "[INFO] Axwins frontend local startup"
Write-Host "[INFO] Frontend dir: $FrontendDir"
Write-Host "[INFO] REACT_APP_BACKEND_URL=$env:REACT_APP_BACKEND_URL"
Write-Host "[INFO] Starting CRA dev server at http://localhost:3000"
npm start
