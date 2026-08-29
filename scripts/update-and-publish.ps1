param(
  [switch]$DryRun,
  [string]$ProductionUrl = "https://arbitrage-dashboard-588.pages.dev/"
)

$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDirectory = Join-Path $projectRoot ".runtime"
$outputPath = Join-Path $projectRoot "app\data\arbitrage.json"
$sharedRoot = if ($env:E_SHARED_DATA_ROOT) { $env:E_SHARED_DATA_ROOT } else { "E:\data" }
$reportPath = Join-Path $sharedRoot "reports\arbitrage_dashboard_integrity.json"
$pythonPath = "D:\anaconda\python.exe"
$statusPath = Join-Path $runtimeDirectory "cloud-publish-status.json"
$startedAt = Get-Date
$runStamp = $startedAt.ToString("yyyyMMdd-HHmmss")
$logPath = Join-Path $runtimeDirectory "cloud-publish-$runStamp.log"
$currentDataDate = $null

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

function Write-PublishLog {
  param([string]$Message)

  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

function Write-RunStatus {
  param(
    [string]$Status,
    [string]$Message,
    [AllowNull()][string]$DataDate
  )

  $payload = [ordered]@{
    status = $Status
    message = $Message
    dataDate = $DataDate
    startedAt = $startedAt.ToString("o")
    finishedAt = (Get-Date).ToString("o")
    logPath = $logPath
  }
  $payload | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}

function Resolve-CommandPath {
  param(
    [string]$Name,
    [AllowNull()][string]$Fallback = $null
  )

  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }
  if ($Fallback -and (Test-Path -LiteralPath $Fallback)) {
    return $Fallback
  }
  throw "找不到命令：$Name"
}

function Invoke-LoggedCommand {
  param(
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$Step
  )

  Write-PublishLog "开始：$Step"
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $commandOutput = & $FilePath @ArgumentList 2>&1
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousPreference
  }

  foreach ($line in $commandOutput) {
    Add-Content -LiteralPath $logPath -Value ("  " + [string]$line) -Encoding UTF8
  }
  if ($exitCode -ne 0) {
    throw "$Step 失败，退出码 $exitCode；详见 $logPath"
  }
  Write-PublishLog "完成：$Step"
  return @($commandOutput)
}

function Get-JsonDataDate {
  param([string]$JsonText)

  $matched = [regex]::Match($JsonText, '"dataDate"\s*:\s*"(?<date>\d{4}-\d{2}-\d{2})"')
  if (-not $matched.Success) {
    throw "数据文件缺少 dataDate"
  }
  return $matched.Groups["date"].Value
}

function Read-Utf8Text {
  param([string]$Path)

  return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Assert-RepositoryReady {
  param(
    [string]$GitPath,
    [switch]$SkipFetch
  )

  $branch = (& $GitPath -C $projectRoot branch --show-current).Trim()
  if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
    throw "自动发布只允许在 main 分支运行，当前分支为：$branch"
  }

  $stagedPaths = @(& $GitPath -C $projectRoot diff --cached --name-only) | Where-Object { $_ }
  if ($LASTEXITCODE -ne 0) {
    throw "无法检查暂存区"
  }
  if ($stagedPaths.Count -gt 0) {
    throw "暂存区存在用户修改，自动发布已停止：$($stagedPaths -join ', ')"
  }

  $trackedChanges = @(& $GitPath -C $projectRoot diff --name-only) | Where-Object {
    $_ -and $_ -ne "app/data/arbitrage.json"
  }
  if ($LASTEXITCODE -ne 0) {
    throw "无法检查工作区修改"
  }
  if ($trackedChanges.Count -gt 0) {
    throw "存在数据文件以外的已跟踪修改，自动发布已停止：$($trackedChanges -join ', ')"
  }

  if (-not $SkipFetch) {
    Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "fetch", "origin", "main", "--quiet") -Step "同步远端状态"
    $syncCounts = (& $GitPath -C $projectRoot rev-list --left-right --count "origin/main...HEAD").Trim() -split "\s+"
    if ($LASTEXITCODE -ne 0 -or $syncCounts.Count -ne 2) {
      throw "无法比较本地 main 与 origin/main"
    }
    if ($syncCounts[0] -ne "0" -or $syncCounts[1] -ne "0") {
      throw "本地 main 与 origin/main 不同步（远端领先 $($syncCounts[0])，本地领先 $($syncCounts[1])），请人工处理"
    }
  }
}

function Assert-IntegrityReport {
  if (-not (Test-Path -LiteralPath $reportPath)) {
    throw "完整性报告不存在：$reportPath"
  }

  $report = Read-Utf8Text -Path $reportPath | ConvertFrom-Json
  $checks = @(
    ($report.status -eq "ok")
    ([int]$report.pairCount -eq 37)
    ([int]$report.expectedPairCount -eq 37)
    ([int]$report.pairCount -eq [int]$report.expectedPairCount)
    ($report.futureDataDetected -eq $false)
    ($report.hierarchySorted -eq $true)
    ($report.relatedObservationsComplete -eq $true)
    ($report.externalSourcesComplete -eq $true)
  )
  if ($checks -contains $false) {
    throw "完整性校验未通过：status=$($report.status)，pairCount=$($report.pairCount)/$($report.expectedPairCount)，futureDataDetected=$($report.futureDataDetected)，hierarchySorted=$($report.hierarchySorted)，relatedObservationsComplete=$($report.relatedObservationsComplete)，externalSourcesComplete=$($report.externalSourcesComplete)"
  }

  if (-not (Test-Path -LiteralPath $outputPath)) {
    throw "看板数据文件不存在：$outputPath"
  }
  $outputDate = Get-JsonDataDate -JsonText (Read-Utf8Text -Path $outputPath)
  if ($outputDate -ne [string]$report.dataDate) {
    throw "数据文件日期 $outputDate 与完整性报告日期 $($report.dataDate) 不一致"
  }
  return $outputDate
}

function Wait-ForCloudflareSnapshot {
  param([string]$ExpectedDataDate)

  $deadline = (Get-Date).AddMinutes(15)
  while ((Get-Date) -lt $deadline) {
    try {
      $headers = @{ "Cache-Control" = "no-cache" }
      $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
      $separator = if ($ProductionUrl.Contains("?")) { "&" } else { "?" }
      $response = Invoke-WebRequest -Uri "$ProductionUrl${separator}v=$cacheBust" -Headers $headers -UseBasicParsing -TimeoutSec 30
      if ($response.StatusCode -eq 200 -and $response.Content.Contains($ExpectedDataDate) -and $response.Content.Contains("套利监测看板")) {
        Write-PublishLog "Cloudflare 已展示数据日 $ExpectedDataDate"
        return
      }
    } catch {
      Write-PublishLog "等待 Cloudflare 时暂未成功：$($_.Exception.Message)"
    }
    Start-Sleep -Seconds 20
  }
  throw "GitHub 已推送，但 15 分钟内未确认 Cloudflare 展示数据日 $ExpectedDataDate"
}

trap {
  $message = $_.Exception.Message
  Write-PublishLog "失败：$message"
  Write-RunStatus -Status "failed" -Message $message -DataDate $currentDataDate
  exit 1
}

Set-Location -LiteralPath $projectRoot
Write-PublishLog "套利看板自动更新任务启动。DryRun=$DryRun"

if (-not (Test-Path -LiteralPath $pythonPath)) {
  throw "找不到指定 Python：$pythonPath"
}
$gitPath = Resolve-CommandPath -Name "git.exe"
$npmPath = Resolve-CommandPath -Name "npm.cmd" -Fallback (Join-Path $env:ProgramFiles "nodejs\npm.cmd")

Assert-RepositoryReady -GitPath $gitPath -SkipFetch:$DryRun

$committedJson = @(& $gitPath -C $projectRoot show "HEAD:app/data/arbitrage.json") -join "`n"
if ($LASTEXITCODE -ne 0) {
  throw "无法读取 HEAD 中的 app/data/arbitrage.json"
}
$committedDataDate = Get-JsonDataDate -JsonText $committedJson

if ($DryRun) {
  $currentDataDate = Assert-IntegrityReport
  $message = "演练通过：环境、仓库和完整性报告可用；未更新、未提交、未推送"
  Write-PublishLog $message
  Write-RunStatus -Status "dry_run_ok" -Message $message -DataDate $currentDataDate
  exit 0
}

Invoke-LoggedCommand -FilePath $pythonPath -ArgumentList @("scripts\update_xtdata.py") -Step "更新 xtdata 与已批准外部补充数据"
$currentDataDate = Assert-IntegrityReport

if ($currentDataDate -eq $committedDataDate) {
  $message = "无新交易日数据：HEAD 与当前数据日均为 $currentDataDate"
  Write-PublishLog $message
  Write-RunStatus -Status "no_new_data" -Message $message -DataDate $currentDataDate
  exit 0
}

Invoke-LoggedCommand -FilePath $npmPath -ArgumentList @("run", "test:pages") -Step "构建并验证 Cloudflare 静态页面"
Assert-RepositoryReady -GitPath $gitPath -SkipFetch

Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "add", "--", "app/data/arbitrage.json") -Step "暂存看板数据"
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "commit", "-m", "data: update arbitrage dashboard to $currentDataDate") -Step "提交数据快照"
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "push", "origin", "main") -Step "推送 main 并触发 Cloudflare"

Wait-ForCloudflareSnapshot -ExpectedDataDate $currentDataDate
$message = "更新成功：数据日 $currentDataDate 已推送并在 Cloudflare 生效"
Write-PublishLog $message
Write-RunStatus -Status "success" -Message $message -DataDate $currentDataDate
exit 0
