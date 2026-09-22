param(
  [switch]$DryRun,
  [switch]$RecoverOnly,
  [switch]$Scheduled,
  [string]$ProductionUrl = "https://arbitrage-dashboard-588.pages.dev/"
)

$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
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
$publisherBranch = "automation/publisher"
$pendingPath = Join-Path $runtimeDirectory "cloud-publish-pending.json"
$completedPath = Join-Path $runtimeDirectory "cloud-publish-completed.json"
$script:publishStage = "preflight"
$script:publishStep = ""
$script:unpublishedDataCommit = $false
$publishLock = $null

. (Join-Path $PSScriptRoot "publisher-support.ps1")
$script:cycleDate = Get-PublisherCycleDate

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
    [AllowNull()][string]$DataDate,
    [bool]$Retryable = $false
  )

  $payload = [ordered]@{
    status = $Status
    message = $Message
    dataDate = $DataDate
    cycleDate = $script:cycleDate
    stage = $script:publishStage
    step = $script:publishStep
    retryable = $Retryable
    startedAt = $startedAt.ToString("o")
    finishedAt = $(if ($Status -eq "running") { $null } else { (Get-Date).ToString("o") })
    logPath = $logPath
  }
  Write-PublisherState -Path $statusPath -Value $payload
}

function Set-PublishStage {
  param([string]$Stage)
  $script:publishStage = $Stage
  Write-RunStatus -Status "running" -Message "正在执行：$Stage" -DataDate $currentDataDate
}

function Show-DashboardNotification {
  param(
    [string]$Title,
    [string]$Message
  )

  try {
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
    $textNodes = $xml.GetElementsByTagName("text")
    [void]$textNodes.Item(0).AppendChild($xml.CreateTextNode($Title))
    [void]$textNodes.Item(1).AppendChild($xml.CreateTextNode($Message))
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("套利监测看板").Show($toast)
  } catch {
    Write-PublishLog "Windows 失败通知未显示：$($_.Exception.Message)"
  }
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
    [string]$Step,
    [switch]$RetryGitNetwork,
    [ValidateRange(1, 6)]
    [int]$MaxAttempts = 4
  )

  $attemptLimit = if ($RetryGitNetwork) { $MaxAttempts } else { 1 }
  $script:publishStep = $Step
  for ($attempt = 1; $attempt -le $attemptLimit; $attempt++) {
    [string[]]$commandArguments = if ($RetryGitNetwork) {
      # Re-read the user's current local proxy on each retry; do not persist Git config.
      @(Get-PublisherGitNetworkOptions) + $ArgumentList
    } else { $ArgumentList }
    Write-PublishLog "开始：$Step（第 $attempt/$attemptLimit 次）"
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      $commandOutput = @(& $FilePath @commandArguments 2>&1)
      $exitCode = $LASTEXITCODE
    } finally {
      $ErrorActionPreference = $previousPreference
    }

    foreach ($line in $commandOutput) {
      Add-Content -LiteralPath $logPath -Value ("  " + [string]$line) -Encoding UTF8
    }
    if ($exitCode -eq 0) {
      Write-PublishLog "完成：$Step"
      return $commandOutput
    }

    $failureText = ($commandOutput | ForEach-Object { [string]$_ }) -join "`n"
    $isTransient = $failureText -match '(?i)connection (?:was )?reset|recv failure|send failure|could not resolve (?:host|proxy)|failed to connect|couldn.t connect|timed? out|timeout|operation too slow|remote end hung up|unexpected disconnect|early EOF|HTTP/?[0-9.]* (?:500|502|503|504)|returned error: (?:500|502|503|504)'
    $isPermanent = $failureText -match '(?i)authentication failed|permission denied|could not read Username|repository not found|non-fast-forward|fetch first|certificate|returned error: (?:401|403|404)'
    if (-not $RetryGitNetwork -or -not $isTransient -or $isPermanent -or $attempt -eq $attemptLimit) {
      $failure = New-Object System.Exception("$Step 失败，退出码 $exitCode，已尝试 $attempt 次；详见 $logPath")
      $failure.Data["Retryable"] = [bool]($RetryGitNetwork -and $isTransient -and -not $isPermanent)
      throw $failure
    }
    $delaySeconds = [int][Math]::Min(5 * [Math]::Pow(2, $attempt - 1), 60)
    Write-PublishLog "网络暂时失败：$Step；$delaySeconds 秒后重试。"
    Start-Sleep -Seconds $delaySeconds
  }
}

function Get-JsonDataDate {
  param([string]$JsonText)

  $matched = [regex]::Match($JsonText, '"dataDate"\s*:\s*"(?<date>\d{4}-\d{2}-\d{2})"')
  if (-not $matched.Success) {
    throw "数据文件缺少 dataDate"
  }
  return $matched.Groups["date"].Value
}

function Get-JsonUpdatedAt {
  param([string]$JsonText)

  $matched = [regex]::Match($JsonText, '"updatedAt"\s*:\s*"(?<timestamp>[^"]+)"')
  if (-not $matched.Success) {
    throw "数据文件缺少 updatedAt"
  }
  return $matched.Groups["timestamp"].Value
}

function Read-Utf8Text {
  param([string]$Path)

  return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Get-NormalizedJsonHash {
  param([string]$JsonText)

  $payload = $JsonText | ConvertFrom-Json
  $payload.PSObject.Properties.Remove("updatedAt")
  $normalized = $payload | ConvertTo-Json -Depth 100 -Compress
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalized)
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    return -join ($sha256.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
  } finally {
    $sha256.Dispose()
  }
}

function Assert-RepositoryReady {
  param(
    [string]$GitPath,
    [switch]$SkipFetch
  )

  $branch = (& $GitPath -C $projectRoot branch --show-current).Trim()
  if ($LASTEXITCODE -ne 0 -or $branch -notin @("main", $publisherBranch)) {
    throw "自动发布只允许在 main 或 $publisherBranch 分支运行，当前分支为：$branch"
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
    Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "fetch", "origin", "main", "--quiet") -Step "同步远端状态" -RetryGitNetwork | Out-Null
    $syncCounts = (& $GitPath -C $projectRoot rev-list --left-right --count "origin/main...HEAD").Trim() -split "\s+"
    if ($LASTEXITCODE -ne 0 -or $syncCounts.Count -ne 2) {
      throw "无法比较本地 main 与 origin/main"
    }
    $remoteAhead = [int]$syncCounts[0]
    $localAhead = [int]$syncCounts[1]
    if ($branch -eq $publisherBranch) {
      if ($remoteAhead -gt 0 -and $localAhead -gt 0) {
        throw "独立发布分支与 origin/main 已分叉（远端领先 $remoteAhead，本地领先 $localAhead），请人工处理"
      }
      if ($remoteAhead -gt 0) {
        if ((& $GitPath -C $projectRoot diff --name-only -- "app/data/arbitrage.json")) {
          Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "restore", "--source=HEAD", "--", "app/data/arbitrage.json") -Step "清理独立发布目录中的未发布生成文件"
        }
        Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "merge", "--ff-only", "origin/main") -Step "快进独立发布分支"
      } elseif ($localAhead -gt 0) {
        $aheadPaths = @(& $GitPath -C $projectRoot log --format= --name-only "origin/main..HEAD") | Where-Object { $_ }
        if ($aheadPaths.Count -eq 0 -or ($aheadPaths | Where-Object { $_ -ne "app/data/arbitrage.json" }).Count -gt 0) {
          throw "独立发布分支存在非数据提交，自动恢复已停止：$($aheadPaths -join ', ')"
        }
        $script:unpublishedDataCommit = $true
      }
    } elseif ($remoteAhead -ne 0 -or $localAhead -ne 0) {
      throw "本地 main 与 origin/main 不同步（远端领先 $remoteAhead，本地领先 $localAhead），请人工处理"
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
    ($report.indexTermHistoryComplete -eq $true)
    ($report.indexTermThresholdsComplete -eq $true)
    ([int]$report.pairCount -eq [int]$report.expectedPairCount)
    ($report.futureDataDetected -eq $false)
    ($report.hierarchySorted -eq $true)
    ($report.relatedObservationsComplete -eq $true)
    ($report.fundingPressureOverlayComplete -eq $true)
    ($report.riskPremiumOverlaysComplete -eq $true)
    ($report.imIfSpotOverlayComplete -eq $true)
    ($report.imIfSpotThresholdsComplete -eq $true)
    ($report.imIcSpotOverlayComplete -eq $true)
    ($report.icIfSpotOverlayComplete -eq $true)
    ($report.icIfSpotThresholdsComplete -eq $true)
    ($report.aluminumAlloySpreadComplete -eq $true)
    ($report.spotCorrelationMetricsComplete -eq $true)
    ($report.fullDailyChartStatisticsComplete -eq $true)
    ($report.domesticFreshnessComplete -eq $true)
    ($report.externalRowDatesComplete -eq $true)
    ($report.externalSourcesComplete -eq $true)
  )
  if ($checks -contains $false) {
    throw "完整性校验未通过：status=$($report.status)，pairCount=$($report.pairCount)/$($report.expectedPairCount)，dataDate=$($report.dataDate)，expectedDomesticDataDate=$($report.expectedDomesticDataDate)，domesticFreshnessComplete=$($report.domesticFreshnessComplete)，futureDataDetected=$($report.futureDataDetected)，hierarchySorted=$($report.hierarchySorted)，relatedObservationsComplete=$($report.relatedObservationsComplete)，fundingPressureOverlayComplete=$($report.fundingPressureOverlayComplete)，riskPremiumOverlaysComplete=$($report.riskPremiumOverlaysComplete)，imIfSpotOverlayComplete=$($report.imIfSpotOverlayComplete)，imIfSpotThresholdsComplete=$($report.imIfSpotThresholdsComplete)，imIcSpotOverlayComplete=$($report.imIcSpotOverlayComplete)，icIfSpotOverlayComplete=$($report.icIfSpotOverlayComplete)，icIfSpotThresholdsComplete=$($report.icIfSpotThresholdsComplete)，aluminumAlloySpreadComplete=$($report.aluminumAlloySpreadComplete)，indexTermThresholdsComplete=$($report.indexTermThresholdsComplete)，spotCorrelationMetricsComplete=$($report.spotCorrelationMetricsComplete)，fullDailyChartStatisticsComplete=$($report.fullDailyChartStatisticsComplete)，externalRowDatesComplete=$($report.externalRowDatesComplete)，externalSourcesComplete=$($report.externalSourcesComplete)"
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
  param(
    [string]$ExpectedDataDate,
    [string]$ExpectedUpdatedAt
  )

  $deadline = (Get-Date).AddMinutes(15)
  while ((Get-Date) -lt $deadline) {
    try {
      $headers = @{ "Cache-Control" = "no-cache" }
      $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
      $separator = if ($ProductionUrl.Contains("?")) { "&" } else { "?" }
      $response = Invoke-WebRequest -Uri "$ProductionUrl${separator}v=$cacheBust" -Headers $headers -UseBasicParsing -TimeoutSec 30
      $snapshotMatch = [regex]::Match($response.Content, 'data-snapshot-updated-at="([^"]+)"')
      if ($response.StatusCode -eq 200 -and $snapshotMatch.Success -and $snapshotMatch.Groups[1].Value -eq $ExpectedUpdatedAt -and $response.Content.Contains($ExpectedDataDate) -and $response.Content.Contains("套利监测看板")) {
        Write-PublishLog "Cloudflare 已展示国内数据日 $ExpectedDataDate，快照时间 $ExpectedUpdatedAt"
        return
      }
    } catch {
      Write-PublishLog "等待 Cloudflare 时暂未成功：$($_.Exception.Message)"
    }
    Start-Sleep -Seconds 20
  }
  $failure = New-Object System.Exception("GitHub 已推送，但 15 分钟内未确认 Cloudflare 展示国内数据日 $ExpectedDataDate 与快照时间 $ExpectedUpdatedAt")
  $failure.Data["Retryable"] = $true
  throw $failure
}

function Resume-PublisherSnapshot {
  param([object]$Snapshot, [object]$Pending)
  Set-PublishStage -Stage "recover"
  & $gitPath -C $projectRoot diff --quiet -- "app/data/arbitrage.json"
  if ($LASTEXITCODE -ne 0) { throw "恢复发布前发现未提交的数据修改，停止以保留现有内容" }
  if ($Pending) { Assert-PublisherPendingSnapshot -Pending $Pending -Snapshot $Snapshot }
  $recoveryCycle = if ($Pending) { $Pending.cycleDate } else { $Snapshot.cycleDate }
  if (-not $Pending -or $Pending.commit -ne $Snapshot.commit) {
    $null = Assert-IntegrityReport
    Set-PublishStage -Stage "build"
    Invoke-LoggedCommand -FilePath $npmPath -ArgumentList @("run", "test:pages") -Step "验证待补发快照" | Out-Null
    Save-PublisherPending -Snapshot $Snapshot -CycleDate $recoveryCycle -Path $pendingPath
  }
  if ($script:unpublishedDataCommit) {
    Set-PublishStage -Stage "push"
    Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "push", "origin", "HEAD:main") -Step "补推已校验的数据提交" -RetryGitNetwork | Out-Null
  }
  Set-PublishStage -Stage "verify"
  Wait-ForCloudflareSnapshot -ExpectedDataDate $Snapshot.dataDate -ExpectedUpdatedAt $Snapshot.updatedAt
  $message = "补发完成：国内数据日 $($Snapshot.dataDate)，快照 $($Snapshot.updatedAt) 已在线核验；未重复下载行情"
  Write-PublishLog $message
  Write-RunStatus -Status "success" -Message $message -DataDate $Snapshot.dataDate
  Save-PublisherCompletion -Snapshot $Snapshot -CycleDate $recoveryCycle -CompletedPath $completedPath -PendingPath $pendingPath
  return $recoveryCycle
}

trap {
  $rawMessage = $_.Exception.Message
  $message = if ($rawMessage.Length -gt 1000) { $rawMessage.Substring(0, 1000) + "…" } else { $rawMessage }
  $notificationMessage = if ($message.Length -gt 180) { $message.Substring(0, 180) + "…" } else { $message }
  Write-PublishLog "失败：$message"
  $retryable = if ($_.Exception.Data.Contains("Retryable")) { [bool]$_.Exception.Data["Retryable"] } else { $script:publishStage -in @("update", "verify") }
  Write-RunStatus -Status "failed" -Message $message -DataDate $currentDataDate -Retryable $retryable
  Show-DashboardNotification -Title "套利看板自动更新失败" -Message $notificationMessage
  if ($publishLock) { $publishLock.Dispose() }
  exit 1
}

Set-Location -LiteralPath $projectRoot
try {
  $publishLock = [IO.File]::Open((Join-Path $runtimeDirectory "cloud-publish.lock"), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
} catch [IO.IOException] {
  Write-Output "已有套利看板更新任务运行，跳过重复启动。"
  exit 0
}
$previousStatus = Read-PublisherState -Path $statusPath
$completed = Read-PublisherState -Path $completedPath
if ($Scheduled -and -not $DryRun -and -not (Test-PublisherScheduledWork -CycleDate $script:cycleDate -Completed $completed -LastStatus $previousStatus -HasPending (Test-Path -LiteralPath $pendingPath))) {
  $publishLock.Dispose()
  exit 0
}
Write-PublishLog "套利看板自动更新任务启动。DryRun=$DryRun；RecoverOnly=$RecoverOnly；Scheduled=$Scheduled"

if (-not (Test-Path -LiteralPath $pythonPath)) {
  throw "找不到指定 Python：$pythonPath"
}
$gitPath = Resolve-CommandPath -Name "git.exe"
$npmPath = Resolve-CommandPath -Name "npm.cmd" -Fallback (Join-Path $env:ProgramFiles "nodejs\npm.cmd")
Initialize-PublisherNetwork -GitPath $gitPath -ProjectRoot $projectRoot

if (-not $DryRun) { Set-PublishStage -Stage "sync" }
Assert-RepositoryReady -GitPath $gitPath -SkipFetch:$DryRun

$committedSnapshot = Get-PublisherHeadSnapshot -GitPath $gitPath -ProjectRoot $projectRoot
$committedDataDate = $committedSnapshot.dataDate
$committedUpdatedAt = $committedSnapshot.updatedAt
$committedContentHash = $committedSnapshot.dataHash

if ($DryRun) {
  $currentDataDate = Assert-IntegrityReport
  $message = "演练通过：环境、仓库和完整性报告可用；未更新、未提交、未推送"
  Write-PublishLog $message
  Write-RunStatus -Status "dry_run_ok" -Message $message -DataDate $currentDataDate
  $publishLock.Dispose()
  exit 0
}

$pending = Read-PublisherState -Path $pendingPath
$legacyRecovery = $Scheduled -and $previousStatus.status -eq "failed" -and $previousStatus.dataDate -eq $committedDataDate
if ($RecoverOnly -or $pending -or $script:unpublishedDataCommit -or $legacyRecovery) {
  $currentDataDate = $committedDataDate
  $recoveredCycle = Resume-PublisherSnapshot -Snapshot $committedSnapshot -Pending $pending
  if ($RecoverOnly -or $recoveredCycle -ge $script:cycleDate) {
    $publishLock.Dispose()
    exit 0
  }
}

Set-PublishStage -Stage "update"
Invoke-LoggedCommand -FilePath $pythonPath -ArgumentList @("scripts\update_xtdata.py") -Step "更新 xtdata 与已批准外部补充数据" | Out-Null
$currentDataDate = Assert-IntegrityReport
$currentJson = Read-Utf8Text -Path $outputPath
$currentUpdatedAt = Get-JsonUpdatedAt -JsonText $currentJson
$currentContentHash = Get-NormalizedJsonHash -JsonText $currentJson

if ([datetime]$currentDataDate -lt [datetime]$committedDataDate) {
  throw "生成数据日 $currentDataDate 早于 HEAD 数据日 $committedDataDate"
}

if ($currentContentHash -eq $committedContentHash) {
  Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "restore", "--source=HEAD", "--", "app/data/arbitrage.json") -Step "清理无实质变化的生成文件"
  Save-PublisherPending -Snapshot $committedSnapshot -CycleDate $script:cycleDate -Path $pendingPath
  Set-PublishStage -Stage "verify"
  Wait-ForCloudflareSnapshot -ExpectedDataDate $committedDataDate -ExpectedUpdatedAt $committedUpdatedAt
  $message = "无实质数据变化且线上快照已验证：国内数据日仍为 $currentDataDate，外部来源内容也未变化"
  Write-PublishLog $message
  Write-RunStatus -Status "no_new_data" -Message $message -DataDate $currentDataDate
  Save-PublisherCompletion -Snapshot $committedSnapshot -CycleDate $script:cycleDate -CompletedPath $completedPath -PendingPath $pendingPath
  $publishLock.Dispose()
  exit 0
}

Set-PublishStage -Stage "build"
Invoke-LoggedCommand -FilePath $npmPath -ArgumentList @("run", "test:pages") -Step "构建并验证 Cloudflare 静态页面" | Out-Null
Assert-RepositoryReady -GitPath $gitPath -SkipFetch

Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "add", "--", "app/data/arbitrage.json") -Step "暂存看板数据"
$commitMessage = if ($currentDataDate -ne $committedDataDate) {
  "data: update arbitrage dashboard to $currentDataDate"
} else {
  "data: refresh arbitrage dashboard sources for $currentDataDate"
}
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "commit", "-m", $commitMessage) -Step "提交数据快照"
$newSnapshot = Get-PublisherHeadSnapshot -GitPath $gitPath -ProjectRoot $projectRoot
Save-PublisherPending -Snapshot $newSnapshot -CycleDate $script:cycleDate -Path $pendingPath
$pushRef = if ((& $gitPath -C $projectRoot branch --show-current).Trim() -eq $publisherBranch) { "HEAD:main" } else { "main" }
Set-PublishStage -Stage "push"
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "push", "origin", $pushRef) -Step "推送 main 并触发 Cloudflare" -RetryGitNetwork | Out-Null

Set-PublishStage -Stage "verify"
Wait-ForCloudflareSnapshot -ExpectedDataDate $currentDataDate -ExpectedUpdatedAt $currentUpdatedAt
$message = "更新成功：数据日 $currentDataDate 已推送并在 Cloudflare 生效"
Write-PublishLog $message
Write-RunStatus -Status "success" -Message $message -DataDate $currentDataDate
Save-PublisherCompletion -Snapshot $newSnapshot -CycleDate $script:cycleDate -CompletedPath $completedPath -PendingPath $pendingPath
$publishLock.Dispose()
exit 0
