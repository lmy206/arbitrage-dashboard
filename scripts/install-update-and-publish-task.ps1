param(
  [string]$TaskName = "ArbitrageDashboardCloudPublish",
  [string]$PublisherRoot = "D:\arbitrage-dashboard-publisher"
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitPath = (Get-Command git.exe -ErrorAction Stop).Source
. (Join-Path $PSScriptRoot "publisher-support.ps1")
function Write-PublishLog { param([string]$Message) Write-Host $Message }
Initialize-PublisherNetwork -GitPath $gitPath -ProjectRoot $sourceRoot
[string[]]$networkOptions = @(Get-PublisherGitNetworkOptions)
& $gitPath @networkOptions -C $sourceRoot fetch origin main --quiet
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

$sourceNodeModules = Join-Path $sourceRoot "node_modules"
$publisherNodeModules = Join-Path $PublisherRoot "node_modules"
if (-not (Test-Path -LiteralPath $sourceNodeModules)) {
  throw "主项目缺少 node_modules，请先在 $sourceRoot 运行 npm install"
}
if (-not (Test-Path -LiteralPath $publisherNodeModules)) {
  New-Item -ItemType Junction -Path $publisherNodeModules -Target $sourceNodeModules | Out-Null
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
$repeatPattern = New-ScheduledTaskTrigger `
  -Once `
  -At "20:10" `
  -RepetitionInterval (New-TimeSpan -Minutes 10) `
  -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 50)
$trigger.Repetition = $repeatPattern.Repetition
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

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
  if ($existingTask.State -eq "Running") { throw "计划任务仍在运行，不能覆盖任务配置" }
  # Keep the task's existing account and execution/security settings.
  $principal = $existingTask.Principal
  $settings = $existingTask.Settings
  $backupDirectory = Join-Path $sourceRoot ".runtime"
  New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
  $backupPath = Join-Path $backupDirectory ("cloud-publish-task-before-{0}.xml" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
  [IO.File]::WriteAllText($backupPath, (Export-ScheduledTask -TaskName $TaskName), [Text.Encoding]::Unicode)
}

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "工作日20:10更新；每10分钟检查未完成发布，成功后本轮空跑跳过；使用独立worktree推送GitHub并核验Cloudflare" `
  -Force | Out-Null

Get-ScheduledTask -TaskName $TaskName
