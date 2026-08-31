param(
  [string]$TaskName = "ArbitrageDashboardCloudPublish",
  [string]$PublisherRoot = "D:\arbitrage-dashboard-publisher"
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitPath = (Get-Command git.exe -ErrorAction Stop).Source
& $gitPath -C $sourceRoot fetch origin main --quiet
if ($LASTEXITCODE -ne 0) {
  throw "无法同步 origin/main，未更新计划任务"
}

$publisherGit = Join-Path $PublisherRoot ".git"
if (-not (Test-Path -LiteralPath $publisherGit)) {
  if (Test-Path -LiteralPath $PublisherRoot) {
    throw "独立发布目录已存在但不是 Git worktree：$PublisherRoot"
  }
  & $gitPath -C $sourceRoot show-ref --verify --quiet "refs/heads/automation/publisher"
  if ($LASTEXITCODE -eq 0) {
    & $gitPath -C $sourceRoot worktree add $PublisherRoot "automation/publisher"
  } else {
    & $gitPath -C $sourceRoot worktree add -b "automation/publisher" $PublisherRoot "origin/main"
  }
  if ($LASTEXITCODE -ne 0) {
    throw "无法创建独立发布 worktree：$PublisherRoot"
  }
}

$launcherPath = Join-Path $PublisherRoot "scripts\run-update-and-publish-hidden.vbs"
if (-not (Test-Path -LiteralPath $launcherPath)) {
  throw "找不到隐藏启动器：$launcherPath"
}

$wscriptPath = Join-Path $env:SystemRoot "System32\wscript.exe"
$action = New-ScheduledTaskAction `
  -Execute $wscriptPath `
  -Argument "//B //Nologo `"$launcherPath`"" `
  -WorkingDirectory $PublisherRoot
$trigger = New-ScheduledTaskTrigger `
  -Weekly `
  -WeeksInterval 1 `
  -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
  -At "20:10"
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -WakeToRun `
  -RunOnlyIfNetworkAvailable `
  -MultipleInstances IgnoreNew `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 10) `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
  -UserId $identity `
  -LogonType Interactive `
  -RunLevel Limited

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "交易日 20:10 在独立发布 worktree 更新套利看板；校验通过后推送 GitHub main 并触发 Cloudflare Pages" `
  -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName
