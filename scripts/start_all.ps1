[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$BackendPort = 8010,
    [ValidateRange(1, 65535)][int]$FrontendPort = 5180,
    [switch]$WithPerception,
    [string]$CameraSource = 'auto'
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskGame = Join-Path $taskRoot 'apps/game'
$taskVite = Join-Path $taskGame 'node_modules/vite/bin/vite.js'
$taskRuntime = Join-Path $taskRoot '.runtime'
$taskBackend = $null
$taskPerception = $null
$taskPreviousEnv = @{}

if (!(Test-Path -LiteralPath $taskPython)) { throw 'Missing .venv/Scripts/python.exe. Follow README.md dependency setup first.' }
if (!(Test-Path -LiteralPath $taskVite)) { throw 'Missing UI dependencies. Run npm.cmd ci in apps/game first.' }
if ($BackendPort -eq $FrontendPort) { throw 'Backend and frontend ports must differ.' }
foreach ($taskPort in @($BackendPort, $FrontendPort)) {
    $taskListener = Get-NetTCPConnection -State Listen -LocalPort $taskPort -ErrorAction SilentlyContinue
    if ($taskListener) { throw "Port $taskPort is already in use. Stop that server or choose another port; this script never terminates an existing server." }
}
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
foreach ($taskName in @('PYTHONUTF8', 'FLOODSHIFT_SCENARIO', 'VITE_API_URL', 'VITE_SCENARIO_ID')) {
    $taskPreviousEnv[$taskName] = [Environment]::GetEnvironmentVariable($taskName, 'Process')
}

try {
    $env:PYTHONUTF8 = '1'
    $env:FLOODSHIFT_SCENARIO = 'nepal_rasuwa_hot_v1'
    $env:VITE_SCENARIO_ID = $env:FLOODSHIFT_SCENARIO
    $env:VITE_API_URL = "http://127.0.0.1:$BackendPort"
    $taskBackend = Start-Process -FilePath $taskPython -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', $BackendPort) -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRuntime 'backend.stdout.log') -RedirectStandardError (Join-Path $taskRuntime 'backend.stderr.log')
    $taskReady = $false
    for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
        if ($taskBackend.HasExited) { throw "Backend exited. Read $taskRuntime/backend.stderr.log" }
        try {
            $taskHealth = Invoke-RestMethod "$env:VITE_API_URL/health" -TimeoutSec 1
            if ($taskHealth.status -eq 'ok') { $taskReady = $true; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (!$taskReady) { throw "Backend did not become healthy. Read $taskRuntime/backend.stderr.log" }
    $taskScenario = Invoke-RestMethod "$env:VITE_API_URL/scenario" -TimeoutSec 5
    if ($taskScenario.scenario_id -ne $env:VITE_SCENARIO_ID) { throw 'Backend/UI scenario mismatch.' }
    if ($WithPerception) {
        $taskPerception = Start-Process -FilePath $taskPython -ArgumentList @('-m', 'perception.service', '--source', ('"' + $CameraSource.Replace('"', '') + '"'), '--classifier', 'perception.fusion:create_classifier', '--observe-url', "$env:VITE_API_URL/perception/physical", '--status-url', "$env:VITE_API_URL/perception/status", '--no-window') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRuntime 'perception.stdout.log') -RedirectStandardError (Join-Path $taskRuntime 'perception.stderr.log')
        Write-Host "Perception started. Diagnostics: $taskRuntime/perception.stderr.log"
    }
    Write-Host "Operator:  http://localhost:$FrontendPort/operator"
    Write-Host 'Press O on the operator page to show technical controls without restarting the clock.'
    Write-Host "Projector: http://localhost:$FrontendPort/projector (second window of the same browser)"
    Write-Host "Screen rehearsal: http://localhost:$FrontendPort/projector?mode=screen"
    Write-Host 'Ctrl+C stops the UI and the backend started by this script.'
    Push-Location $taskGame
    try { & node $taskVite --host 127.0.0.1 --port $FrontendPort --strictPort }
    finally { Pop-Location }
} finally {
    if ($taskPerception -and !$taskPerception.HasExited) { Stop-Process -Id $taskPerception.Id -ErrorAction SilentlyContinue }
    if ($taskBackend -and !$taskBackend.HasExited) { Stop-Process -Id $taskBackend.Id -ErrorAction SilentlyContinue }
    foreach ($taskName in $taskPreviousEnv.Keys) {
        [Environment]::SetEnvironmentVariable($taskName, $taskPreviousEnv[$taskName], 'Process')
    }
}
