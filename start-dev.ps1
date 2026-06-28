$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$apiDir = Join-Path $root "VladStoneAPI"
$webDir = Join-Path $root "VladStoneWeb"
$devDir = Join-Path $root ".dev"
$pidFile = Join-Path $devDir "pids.json"
$apiUrl = "http://127.0.0.1:8001/api/health"
$webUrl = "http://127.0.0.1:5173"

New-Item -ItemType Directory -Force -Path $devDir | Out-Null

function Stop-ExistingDevProcesses {
    if (Test-Path $pidFile) {
        $pids = Get-Content $pidFile | ConvertFrom-Json
        foreach ($processId in @($pids.api, $pids.web)) {
            if ($processId) {
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                if ($process) {
                    taskkill /PID $processId /T /F | Out-Null
                }
            }
        }
        Remove-Item $pidFile -Force
    }

    foreach ($port in @(8001, 5173)) {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($connection in $connections) {
            $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
            if ($process) {
                taskkill /PID $connection.OwningProcess /T /F | Out-Null
            }
        }
    }
}

function Wait-ForUrl($url, $name) {
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2 | Out-Null
            Write-Host "$name ready: $url"
            return
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "$name did not become ready: $url"
}

Stop-ExistingDevProcesses

if (-not (Test-Path (Join-Path $apiDir ".venv"))) {
    Write-Host "Creating backend virtual environment..."
    python -m venv (Join-Path $apiDir ".venv")
}

Write-Host "Installing backend dependencies..."
& (Join-Path $apiDir ".venv\Scripts\python.exe") -m pip install -e "$apiDir[dev]"

if (-not (Test-Path (Join-Path $webDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Push-Location $webDir
    npm install
    Pop-Location
}

Write-Host "Starting API..."
$api = Start-Process `
    -FilePath (Join-Path $apiDir ".venv\Scripts\python.exe") `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001" `
    -WorkingDirectory $apiDir `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $devDir "api.out.log") `
    -RedirectStandardError (Join-Path $devDir "api.err.log")

Write-Host "Starting Web..."
$web = Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" `
    -WorkingDirectory $webDir `
    -PassThru `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $devDir "web.out.log") `
    -RedirectStandardError (Join-Path $devDir "web.err.log")

@{
    api = $api.Id
    web = $web.Id
} | ConvertTo-Json | Set-Content $pidFile

Wait-ForUrl $apiUrl "API"
Wait-ForUrl $webUrl "Web"

Start-Process $webUrl
Write-Host "VladStone started."
Write-Host "Web: $webUrl"
Write-Host "API: http://127.0.0.1:8001"
Write-Host "Logs: $devDir"
