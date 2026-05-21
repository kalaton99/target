Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BackendBaseUrl = "http://127.0.0.1:8000"
$runId = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$failures = 0

function Write-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )
    Write-Host "[$Level] $Message"
}

function Add-Failure {
    param([Parameter(Mandatory = $true)][string]$Message)
    $script:failures += 1
    Write-Check "FAIL" $Message
}

function Invoke-Api {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Body = $null,
        [hashtable]$Headers = @{}
    )
    $params = @{
        Method = $Method
        Uri = "$BackendBaseUrl$Path"
        Headers = $Headers
        TimeoutSec = 15
    }
    if ($null -ne $Body) {
        $params["ContentType"] = "application/json"
        $params["Body"] = ($Body | ConvertTo-Json -Depth 12)
    }
    return Invoke-RestMethod @params
}

function New-AuthHeaders {
    param([Parameter(Mandatory = $true)][string]$Token)
    return @{ Authorization = "Bearer $Token" }
}

function New-DemoUser {
    param([Parameter(Mandatory = $true)][string]$Prefix)
    $username = "$Prefix$runId"
    $auth = Invoke-Api -Method "POST" -Path "/api/v2/lobby/auth" -Body @{ username = $username }
    return @{
        Username = $username
        UserId = $auth.user_id
        Token = $auth.token
        Headers = New-AuthHeaders -Token $auth.token
    }
}

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Receive-WebSocketText {
    param(
        [Parameter(Mandatory = $true)][System.Net.WebSockets.ClientWebSocket]$Socket,
        [int]$TimeoutSeconds = 10
    )
    $buffer = New-Object byte[] 65536
    $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($TimeoutSeconds))
    $result = $Socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cts.Token).GetAwaiter().GetResult()
    if ($result.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text) {
        throw "Target WebSocket returned non-text frame: $($result.MessageType)"
    }
    return [Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count)
}

function Test-TargetLoop {
    Write-Check "INFO" "Checking Target lobby and WebSocket loop"
    $user = New-DemoUser -Prefix "target"
    $config = Invoke-Api -Method "GET" -Path "/api/v2/lobby/config"
    Assert-True -Condition ([bool]$config.allow_bots) -Message "Target local bots are disabled; set TARGET_ALLOW_BOTS=1."
    $target = 100
    $botCap = [int]$config.bot_count_max_by_target.PSObject.Properties["$target"].Value
    Assert-True -Condition ($botCap -eq 4) -Message "Target $target local demo bot cap should be 4 for a one-human 5-seat table; got $botCap. Restart backend with TARGET_BOT_COUNT_MAX=4."

    $created = Invoke-Api -Method "POST" -Path "/api/v2/lobby/tables" -Headers $user.Headers -Body @{
        name = "Target Local $runId"
        target_score = $target
        stake = 0
        bot_count = $botCap
    }
    $tableId = $created.table_id
    Invoke-Api -Method "POST" -Path "/api/v2/lobby/tables/$tableId/start" -Headers $user.Headers | Out-Null

    $ws = [System.Net.WebSockets.ClientWebSocket]::new()
    $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(10))
    $ws.ConnectAsync([Uri]"ws://127.0.0.1:8000/api/v2/ws/table/$tableId`?token=$($user.Token)", $cts.Token).GetAwaiter().GetResult() | Out-Null
    try {
        Assert-True -Condition ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open) -Message "Target WebSocket did not open."
        $firstMessage = Receive-WebSocketText -Socket $ws
        Assert-True -Condition (($firstMessage -match '"type"\s*:\s*"(WELCOME|STATE_UPDATE|PRIVATE_STATE)"')) -Message "Target WebSocket did not receive an expected live state signal."
        Write-Check "PASS" "Target WebSocket connected and received live state at /api/v2/ws/table/$tableId with $botCap local demo bots"
    } finally {
        if ($ws.State -eq [System.Net.WebSockets.WebSocketState]::Open -or $ws.State -eq [System.Net.WebSockets.WebSocketState]::CloseReceived) {
            try {
                $ws.CloseOutputAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "done", [Threading.CancellationToken]::None).GetAwaiter().GetResult() | Out-Null
            } catch {
                Write-Check "WARN" "Target WebSocket close output was interrupted after successful verification: $($_.Exception.Message)"
            }
        }
        $ws.Dispose()
    }
}

function Test-DicegetLoop {
    Write-Check "INFO" "Checking Diceget create -> auto-fill -> start -> roll -> hold"
    $user = New-DemoUser -Prefix "dice"
    Invoke-Api -Method "GET" -Path "/api/diceget/tables" | Out-Null
    $created = Invoke-Api -Method "POST" -Path "/api/diceget/tables" -Headers $user.Headers -Body @{
        score_goal = 70
        stake = 0
        max_players = 4
    }
    $tableId = $created.table_id
    for ($i = 0; $i -lt 3; $i += 1) {
        Invoke-Api -Method "POST" -Path "/api/diceget/tables/$tableId/add-bot" -Body @{ profile = "safe" } | Out-Null
    }
    $started = Invoke-Api -Method "POST" -Path "/api/diceget/tables/$tableId/start" -Headers $user.Headers
    Assert-True -Condition ($started.status -eq "active") -Message "Diceget table did not become active."
    $rolled = Invoke-Api -Method "POST" -Path "/api/diceget/tables/$tableId/roll" -Headers $user.Headers
    Assert-True -Condition (($rolled.rolls | Measure-Object).Count -gt 0) -Message "Diceget roll history did not update."
    $held = Invoke-Api -Method "POST" -Path "/api/diceget/tables/$tableId/hold" -Headers $user.Headers
    Assert-True -Condition (($held.seats | Where-Object { $_.user_id -eq $user.UserId }).status -eq "held") -Message "Diceget hold did not update the current user's state."
    Write-Check "PASS" "Diceget live API loop completed"
}

function Test-FlipgetLoop {
    Write-Check "INFO" "Checking Flipget create -> choose -> ready -> demo opponent -> Best of 3 flips"
    $user = New-DemoUser -Prefix "flip"
    Invoke-Api -Method "GET" -Path "/api/flipget/tables" | Out-Null
    $created = Invoke-Api -Method "POST" -Path "/api/flipget/tables" -Headers $user.Headers -Body @{
        stake_amount = 0
        max_players = 2
        mode = "best_of_3"
    }
    $tableId = $created.table_id
    Invoke-Api -Method "POST" -Path "/api/flipget/tables/$tableId/choose-side" -Headers $user.Headers -Body @{ side = "heads" } | Out-Null
    Invoke-Api -Method "POST" -Path "/api/flipget/tables/$tableId/ready" -Headers $user.Headers | Out-Null
    $opponent = Invoke-Api -Method "POST" -Path "/api/flipget/tables/$tableId/add-demo-opponent" -Headers $user.Headers -Body @{ username = "Demo Opponent" }
    Assert-True -Condition ($opponent.status -eq "ready") -Message "Flipget demo opponent did not ready the table."
    $flipped = $null
    for ($round = 1; $round -le 3; $round += 1) {
        $flipped = Invoke-Api -Method "POST" -Path "/api/flipget/tables/$tableId/flip" -Headers $user.Headers
        $completedRounds = @($flipped.rounds | Where-Object { $_.result -in @("heads", "tails") })
        Assert-True -Condition (($completedRounds | Measure-Object).Count -ge $round) -Message "Flipget completed round result was missing."
        if ($flipped.status -eq "settled") {
            break
        }
        Assert-True -Condition ($flipped.status -eq "ready") -Message "Flipget Best of 3 did not stay ready for the next flip."
    }
    Assert-True -Condition ($flipped.status -eq "settled") -Message "Flipget Best of 3 table did not settle."
    Assert-True -Condition (($flipped.score.heads -ge 2) -or ($flipped.score.tails -ge 2)) -Message "Flipget Best of 3 did not reach the first-to-2 threshold."
    Write-Check "PASS" "Flipget live API loop completed"
}

function Test-TmargetLoop {
    Write-Check "INFO" "Checking Tmarget create/open -> buy YES -> buy NO"
    $user = New-DemoUser -Prefix "tmarg"
    $headers = $user.Headers.Clone()
    $headers["X-Axwins-Demo-Admin"] = "true"
    Invoke-Api -Method "GET" -Path "/api/tmarget/markets" | Out-Null
    $created = Invoke-Api -Method "POST" -Path "/api/tmarget/admin/markets" -Headers $headers -Body @{
        title = "Local API loop market $runId"
        description = "Internal demo-credit loop verification market."
        category = "Local"
        close_time = "2030-01-01T00:00:00Z"
        resolution_criteria = "Local verification only."
        source_url = ""
        initial_liquidity = 100
    }
    $opened = Invoke-Api -Method "POST" -Path "/api/tmarget/admin/markets/$($created.id)/open" -Headers $headers
    Assert-True -Condition ($opened.status -eq "open") -Message "Tmarget market did not open."
    Invoke-Api -Method "POST" -Path "/api/tmarget/markets/$($created.id)/buy" -Headers $user.Headers -Body @{ outcome = "yes"; shares = 1 } | Out-Null
    Invoke-Api -Method "POST" -Path "/api/tmarget/markets/$($created.id)/buy" -Headers $user.Headers -Body @{ outcome = "no"; shares = 1 } | Out-Null
    $positions = Invoke-Api -Method "GET" -Path "/api/tmarget/markets/$($created.id)/positions" -Headers $user.Headers
    $outcomes = @($positions.positions | ForEach-Object { $_.outcome })
    Assert-True -Condition (($outcomes -contains "yes") -and ($outcomes -contains "no")) -Message "Tmarget YES/NO positions were not visible."
    $market = Invoke-Api -Method "GET" -Path "/api/tmarget/markets/$($created.slug)"
    Assert-True -Condition ([decimal]$market.volume -gt [decimal]$created.volume) -Message "Tmarget market volume did not update."
    Write-Check "PASS" "Tmarget live API loop completed"
}

function Test-WalletLedger {
    Write-Check "INFO" "Checking Wallet / Ledger endpoints"
    $user = New-DemoUser -Prefix "wallet"
    $wallet = Invoke-Api -Method "GET" -Path "/api/platform/wallet/me" -Headers $user.Headers
    $ledger = Invoke-Api -Method "GET" -Path "/api/platform/ledger/me?limit=100" -Headers $user.Headers
    Assert-True -Condition ($null -ne $wallet.balance) -Message "Wallet balance missing."
    Assert-True -Condition ($null -ne $ledger.entries) -Message "Ledger entries missing."
    Write-Check "PASS" "Wallet / Ledger live API endpoints responded"
}

Write-Check "INFO" "Axwins live local product-loop check"
try {
    Invoke-Api -Method "GET" -Path "/api/health" | Out-Null
} catch {
    Add-Failure "Backend is not reachable at $BackendBaseUrl"
    Write-Check "INFO" "Start it with .\scripts\start-backend-local.ps1"
    exit 1
}

foreach ($check in @(
    ${function:Test-TargetLoop},
    ${function:Test-DicegetLoop},
    ${function:Test-FlipgetLoop},
    ${function:Test-TmargetLoop},
    ${function:Test-WalletLedger}
)) {
    try {
        & $check
    } catch {
        Add-Failure $_.Exception.Message
    }
}

if ($failures -gt 0) {
    Write-Check "FAIL" "$failures product loop check(s) failed."
    exit 1
}

Write-Check "PASS" "All live local product-loop API checks passed."
