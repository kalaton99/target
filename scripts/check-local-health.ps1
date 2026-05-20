Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$BackendBaseUrl = "http://127.0.0.1:8000"
$failures = 0

function Write-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )
    Write-Host "[$Level] $Message"
}

function Add-Failure {
    $script:failures += 1
}

function Test-BackendEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $url = "$BackendBaseUrl$Path"
    try {
        $response = & curl.exe --silent --show-error --fail $url 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Check "PASS" "$Name responded at $Path"
            return $true
        }
        Write-Check "FAIL" "$Name did not respond at $Path`: $response"
        Add-Failure
        return $false
    } catch {
        Write-Check "FAIL" "$Name check failed at $Path`: $($_.Exception.Message)"
        Add-Failure
        return $false
    }
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
    Add-Failure
}

$backendReachable = Test-BackendEndpoint -Name "Backend health" -Path "/api/health"
if (-not $backendReachable) {
    Write-Check "FAIL" "Backend is not reachable at $BackendBaseUrl"
    Write-Check "INFO" "Start it with .\scripts\start-backend-local.ps1"
    Write-Check "INFO" "This script does not start or stop services."
    exit 1
}

Test-BackendEndpoint -Name "Diceget tables" -Path "/api/diceget/tables" | Out-Null
Test-BackendEndpoint -Name "Flipget tables" -Path "/api/flipget/tables" | Out-Null
Test-BackendEndpoint -Name "Tmarget markets" -Path "/api/tmarget/markets" | Out-Null
Test-BackendEndpoint -Name "Target lobby config" -Path "/api/v2/lobby/config" | Out-Null

Write-Check "INFO" "This script does not start or stop services."

if ($failures -gt 0) {
    Write-Check "FAIL" "$failures local health check(s) failed."
    exit 1
}

Write-Check "PASS" "Local backend and product endpoints are reachable."
