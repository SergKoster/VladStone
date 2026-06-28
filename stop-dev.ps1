$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root ".dev\pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No VladStone dev processes recorded."
}
else {
    $pids = Get-Content $pidFile | ConvertFrom-Json
    foreach ($processId in @($pids.api, $pids.web)) {
        if ($processId) {
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                taskkill /PID $processId /T /F | Out-Null
                Write-Host "Stopped process $processId"
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
            Write-Host "Stopped process $($connection.OwningProcess) on port $port"
        }
    }
}

Write-Host "VladStone dev processes stopped."
