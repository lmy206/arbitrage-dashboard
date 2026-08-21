param(
  [ValidateRange(1, 65535)]
  [int]$Port = 3001
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDirectory = Join-Path $projectRoot ".runtime"
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

function Write-MonitorLog {
  param([string]$Message)

  $monitorPath = Join-Path $runtimeDirectory "dashboard-monitor.log"
  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -LiteralPath $monitorPath -Value $line -Encoding UTF8
}

function Get-DashboardListener {
  return Get-NetTCPConnection `
    -LocalPort $Port `
    -State Listen `
    -ErrorAction SilentlyContinue `
    | Select-Object -First 1
}

function Test-DashboardResponse {
  try {
    $response = Invoke-WebRequest `
      -Uri "http://localhost:$Port/" `
      -UseBasicParsing `
      -TimeoutSec 5 `
      -ErrorAction Stop

    return $response.StatusCode -eq 200
  } catch {
    return $false
  }
}

function Stop-StalledDashboard {
  param([int]$ProcessId)

  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
  if (-not $process) {
    return $true
  }

  $expectedRoot = [Regex]::Escape($projectRoot)
  if ($process.CommandLine -notmatch $expectedRoot -or $process.CommandLine -notmatch "vinext.*dev.*$Port") {
    Write-MonitorLog "Port $Port is occupied by an unrelated process ($ProcessId); no process was stopped."
    return $false
  }

  Write-MonitorLog "Dashboard process $ProcessId is listening but unhealthy; restarting it."
  Stop-Process -Id $ProcessId -Force -ErrorAction Stop
  Start-Sleep -Seconds 2
  return $true
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  $fallbackNpm = Join-Path $env:ProgramFiles "nodejs\npm.cmd"
  if (-not (Test-Path -LiteralPath $fallbackNpm)) {
    throw "npm.cmd is unavailable. Install Node.js or add it to PATH."
  }
  $npmPath = $fallbackNpm
} else {
  $npmPath = $npmCommand.Source
}

$listener = Get-DashboardListener
if ($listener) {
  if (Test-DashboardResponse) {
    exit 0
  }

  if (-not (Stop-StalledDashboard -ProcessId $listener.OwningProcess)) {
    exit 2
  }
}

$dateStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutPath = Join-Path $runtimeDirectory "dashboard-$dateStamp.stdout.log"
$stderrPath = Join-Path $runtimeDirectory "dashboard-$dateStamp.stderr.log"

Write-MonitorLog "Port $Port is idle; starting the local dashboard."
$process = Start-Process `
  -FilePath $npmPath `
  -ArgumentList @("run", "dev", "--", "--port", $Port) `
  -WorkingDirectory $projectRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutPath `
  -RedirectStandardError $stderrPath `
  -PassThru

Start-Sleep -Seconds 3
if ($process.HasExited) {
  Write-MonitorLog "Dashboard launch failed with code $($process.ExitCode); see $stderrPath."
  exit 1
}

Write-MonitorLog "Dashboard process $($process.Id) started; the next scheduled check will verify HTTP health."
