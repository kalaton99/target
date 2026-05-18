Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )
    Write-Host "[$Level] $Message"
}

Write-Check "INFO" "Axwins local health check"

$mongoService = Get-Service MongoDB -ErrorAction SilentlyContinue
if ($null -eq $mongoService) {
    Write-Check "WARN" "MongoDB service was not found."
} elseif ($mongoService.Status -eq "Running") {
    Write-Check "PASS" "MongoDB service is Running."
} else {
    Write-Check "WARN" "MongoDB service exists but is $($mongoService.Status)."
}

$mongoPort = Test-NetConnection 127.0.0.1 -Port 27017 -WarningAction SilentlyContinue
if ($mongoPort.TcpTestSucceeded) {
    Write-Check "PASS" "MongoDB port 27017 is reachable."
} else {
    Write-Check "FAIL" "MongoDB port 27017 is not reachable."
}

try {
    $health = & curl.exe --silent --show-error --fail http://127.0.0.1:8000/api/health 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Check "PASS" "Backend health endpoint responded: $health"
    } else {
        Write-Check "FAIL" "Backend health endpoint did not respond successfully: $health"
    }
} catch {
    Write-Check "FAIL" "Backend health endpoint check failed: $($_.Exception.Message)"
}

Write-Check "INFO" "This script does not start or stop services."
