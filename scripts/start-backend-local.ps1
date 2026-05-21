Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "[INFO] Axwins backend local startup"
Write-Host "[INFO] Repo root: $RepoRoot"

$mongoService = Get-Service MongoDB -ErrorAction SilentlyContinue
if ($null -eq $mongoService) {
    Write-Host "[WARN] MongoDB service was not found. Confirm local MongoDB is installed and listening on 127.0.0.1:27017."
} elseif ($mongoService.Status -ne "Running") {
    Write-Host "[WARN] MongoDB service exists but is $($mongoService.Status). Start it before using the local backend."
} else {
    Write-Host "[PASS] MongoDB service is Running."
}

$mongoPort = Test-NetConnection 127.0.0.1 -Port 27017 -WarningAction SilentlyContinue
if ($mongoPort.TcpTestSucceeded) {
    Write-Host "[PASS] MongoDB port 27017 is reachable."
} else {
    Write-Host "[WARN] MongoDB port 27017 is not reachable. Backend startup may fail until MongoDB is available."
}

$venvActivate = Join-Path $RepoRoot "backend\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    throw "Backend virtualenv activate script not found: $venvActivate"
}

. $venvActivate

$env:MONGO_URL = "mongodb://127.0.0.1:27017"
$env:DB_NAME = "axwins_local"
$env:JWT_SECRET = "dev-local-jwt-secret-change-later"
$env:RNG_ENCRYPTION_KEY = "dev-local-rng-secret-change-later"
$env:CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
$env:ALLOW_GUEST_AUTH = "1"
$env:TARGET_ALLOW_BOTS = "1"
$env:TARGET_BOT_COUNT_MAX = "4"
$env:TMARGET_DEMO_ADMIN_ENABLED = "1"

Write-Host "[INFO] Starting FastAPI backend at http://127.0.0.1:8000"
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
