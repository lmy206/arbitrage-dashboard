param(
  [switch]$DryRun,
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
    Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "fetch", "origin", "main", "--quiet") -Step "同步远端状态"
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
        $aheadPaths = @(& $GitPath -C $projectRoot diff --name-only "origin/main..HEAD") | Where-Object { $_ }
        if ($aheadPaths.Count -eq 0 -or ($aheadPaths | Where-Object { $_ -ne "app/data/arbitrage.json" }).Count -gt 0) {
          throw "独立发布分支存在非数据提交，自动恢复已停止：$($aheadPaths -join ', ')"
        }
        Invoke-LoggedCommand -FilePath $GitPath -ArgumentList @("-C", $projectRoot, "push", "origin", "HEAD:main") -Step "重试推送上次未完成的数据提交"
        $recoveryJson = @(& $GitPath -C $projectRoot show "HEAD:app/data/arbitrage.json") -join "`n"
        Wait-ForCloudflareSnapshot `
          -ExpectedDataDate (Get-JsonDataDate -JsonText $recoveryJson) `
          -ExpectedUpdatedAt (Get-JsonUpdatedAt -JsonText $recoveryJson)
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
    ([int]$report.pairCount -eq 36)
    ([int]$report.expectedPairCount -eq 36)
    ($report.indexTermHistoryComplete -eq $true)
    ([int]$report.pairCount -eq [int]$report.expectedPairCount)
    ($report.futureDataDetected -eq $false)
    ($report.hierarchySorted -eq $true)
    ($report.relatedObservationsComplete -eq $true)
    ($report.fundingPressureOverlayComplete -eq $true)
    ($report.imIfSpotOverlayComplete -eq $true)
    ($report.imIcSpotOverlayComplete -eq $true)
    ($report.fullDailyChartStatisticsComplete -eq $true)
    ($report.domesticFreshnessComplete -eq $true)
    ($report.externalRowDatesComplete -eq $true)
    ($report.externalSourcesComplete -eq $true)
  )
  if ($checks -contains $false) {
    throw "完整性校验未通过：status=$($report.status)，pairCount=$($report.pairCount)/$($report.expectedPairCount)，dataDate=$($report.dataDate)，expectedDomesticDataDate=$($report.expectedDomesticDataDate)，domesticFreshnessComplete=$($report.domesticFreshnessComplete)，futureDataDetected=$($report.futureDataDetected)，hierarchySorted=$($report.hierarchySorted)，relatedObservationsComplete=$($report.relatedObservationsComplete)，fundingPressureOverlayComplete=$($report.fundingPressureOverlayComplete)，imIfSpotOverlayComplete=$($report.imIfSpotOverlayComplete)，imIcSpotOverlayComplete=$($report.imIcSpotOverlayComplete)，fullDailyChartStatisticsComplete=$($report.fullDailyChartStatisticsComplete)，externalRowDatesComplete=$($report.externalRowDatesComplete)，externalSourcesComplete=$($report.externalSourcesComplete)"
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
      if ($response.StatusCode -eq 200 -and $response.Content.Contains($ExpectedDataDate) -and $response.Content.Contains($ExpectedUpdatedAt) -and $response.Content.Contains("套利监测看板")) {
        Write-PublishLog "Cloudflare 已展示国内数据日 $ExpectedDataDate，快照时间 $ExpectedUpdatedAt"
        return
      }
    } catch {
      Write-PublishLog "等待 Cloudflare 时暂未成功：$($_.Exception.Message)"
    }
    Start-Sleep -Seconds 20
  }
  throw "GitHub 已推送，但 15 分钟内未确认 Cloudflare 展示国内数据日 $ExpectedDataDate 与快照时间 $ExpectedUpdatedAt"
}

trap {
  $rawMessage = $_.Exception.Message
  $message = if ($rawMessage.Length -gt 1000) { $rawMessage.Substring(0, 1000) + "…" } else { $rawMessage }
  $notificationMessage = if ($message.Length -gt 180) { $message.Substring(0, 180) + "…" } else { $message }
  Write-PublishLog "失败：$message"
  Write-RunStatus -Status "failed" -Message $message -DataDate $currentDataDate
  Show-DashboardNotification -Title "套利看板自动更新失败" -Message $notificationMessage
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
$committedUpdatedAt = Get-JsonUpdatedAt -JsonText $committedJson
$committedContentHash = Get-NormalizedJsonHash -JsonText $committedJson

if ($DryRun) {
  $currentDataDate = Assert-IntegrityReport
  $message = "演练通过：环境、仓库和完整性报告可用；未更新、未提交、未推送"
  Write-PublishLog $message
  Write-RunStatus -Status "dry_run_ok" -Message $message -DataDate $currentDataDate
  exit 0
}

Invoke-LoggedCommand -FilePath $pythonPath -ArgumentList @("scripts\update_xtdata.py") -Step "更新 xtdata 与已批准外部补充数据"
$currentDataDate = Assert-IntegrityReport
$currentJson = Read-Utf8Text -Path $outputPath
$currentUpdatedAt = Get-JsonUpdatedAt -JsonText $currentJson
$currentContentHash = Get-NormalizedJsonHash -JsonText $currentJson

if ([datetime]$currentDataDate -lt [datetime]$committedDataDate) {
  throw "生成数据日 $currentDataDate 早于 HEAD 数据日 $committedDataDate"
}

if ($currentContentHash -eq $committedContentHash) {
  Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "restore", "--source=HEAD", "--", "app/data/arbitrage.json") -Step "清理无实质变化的生成文件"
  Wait-ForCloudflareSnapshot -ExpectedDataDate $committedDataDate -ExpectedUpdatedAt $committedUpdatedAt
  $message = "无实质数据变化且线上快照已验证：国内数据日仍为 $currentDataDate，外部来源内容也未变化"
  Write-PublishLog $message
  Write-RunStatus -Status "no_new_data" -Message $message -DataDate $currentDataDate
  exit 0
}

Invoke-LoggedCommand -FilePath $npmPath -ArgumentList @("run", "test:pages") -Step "构建并验证 Cloudflare 静态页面"
Assert-RepositoryReady -GitPath $gitPath -SkipFetch

Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "add", "--", "app/data/arbitrage.json") -Step "暂存看板数据"
$commitMessage = if ($currentDataDate -ne $committedDataDate) {
  "data: update arbitrage dashboard to $currentDataDate"
} else {
  "data: refresh arbitrage dashboard sources for $currentDataDate"
}
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "commit", "-m", $commitMessage) -Step "提交数据快照"
$pushRef = if ((& $gitPath -C $projectRoot branch --show-current).Trim() -eq $publisherBranch) { "HEAD:main" } else { "main" }
Invoke-LoggedCommand -FilePath $gitPath -ArgumentList @("-C", $projectRoot, "push", "origin", $pushRef) -Step "推送 main 并触发 Cloudflare"

Wait-ForCloudflareSnapshot -ExpectedDataDate $currentDataDate -ExpectedUpdatedAt $currentUpdatedAt
$message = "更新成功：数据日 $currentDataDate 已推送并在 Cloudflare 生效"
Write-PublishLog $message
Write-RunStatus -Status "success" -Message $message -DataDate $currentDataDate
exit 0
