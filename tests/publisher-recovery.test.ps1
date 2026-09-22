$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repositoryRoot "scripts\publisher-support.ps1")
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repositoryRoot "scripts\update-and-publish.ps1"), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors.Message -join "; ") }
foreach ($name in @("Resume-PublisherSnapshot", "Assert-RepositoryReady")) {
  $node = $ast.Find({param($candidate) $candidate -is [Management.Automation.Language.FunctionDefinitionAst] -and $candidate.Name -eq $name}, $true)
  if (-not $node) { throw "Missing function $name" }
  . ([scriptblock]::Create($node.Extent.Text))
}

$projectRoot = Join-Path $repositoryRoot (".runtime\publisher-recovery-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $projectRoot | Out-Null
$pendingPath = Join-Path $projectRoot "pending.json"
$completedPath = Join-Path $projectRoot "completed.json"
$gitPath = "Invoke-FakeRecoveryGit"
$npmPath = "test-npm"
$publisherBranch = "automation/publisher"
$script:stages = @()
$script:commands = @()
$script:pushFails = $false
$script:verifyFails = $false
$script:dirtyData = $false
$script:revertedCodeCommit = $false
$script:verifyCount = 0
function Assert-Equal { param($Actual, $Expected, [string]$Label) if (($Actual -join ",") -ne ($Expected -join ",")) { throw "$Label mismatch: $Actual / $Expected" } }
function Write-PublishLog { param([string]$Message) }
function Set-PublishStage { param([string]$Stage) $script:stages += $Stage }
function Write-RunStatus { param($Status,$Message,$DataDate) $script:lastStatus=$Status }
function Assert-IntegrityReport { return "2026-09-22" }
function Wait-ForCloudflareSnapshot {
  param([string]$ExpectedDataDate,[string]$ExpectedUpdatedAt)
  $script:verifyCount++
  Assert-Equal $ExpectedDataDate "2026-09-22" "Recovery date"
  Assert-Equal $ExpectedUpdatedAt "2026-09-22T20:13:57+08:00" "Recovery exact timestamp"
  if ($script:verifyFails) { throw "Cloudflare is temporarily unavailable" }
}
function Invoke-LoggedCommand {
  param([string]$FilePath,[string[]]$ArgumentList,[string]$Step,[switch]$RetryGitNetwork)
  $script:commands += ,$ArgumentList
  if ($script:pushFails -and $ArgumentList -contains "push") { throw "simulated connection reset" }
}
function Invoke-FakeRecoveryGit {
  $global:LASTEXITCODE = 0
  if ($args -contains "--quiet") { if ($script:dirtyData) { $global:LASTEXITCODE=1 }; return }
  if ($args -contains "branch") { return "automation/publisher" }
  if ($args -contains "rev-list") { return "0 1" }
  if ($args -contains "log") { if ($script:revertedCodeCommit) { return @("app/data/arbitrage.json","app/page.tsx") }; return "app/data/arbitrage.json" }
}
$snapshot = [pscustomobject]@{commit="abc123";dataHash="hash-a";dataDate="2026-09-22";updatedAt="2026-09-22T20:13:57+08:00";cycleDate="2026-09-22"}

Save-PublisherPending $snapshot "2026-09-22" $pendingPath
$script:unpublishedDataCommit=$true
$script:pushFails=$true
$caught=$false
try { Resume-PublisherSnapshot $snapshot (Read-PublisherState $pendingPath) | Out-Null } catch { $caught=$true }
Assert-Equal $caught $true "Push failure propagates"
Assert-Equal (Test-Path -LiteralPath $pendingPath) $true "Pending snapshot survives network failure"
Assert-Equal (Test-Path -LiteralPath $completedPath) $false "Failure is not marked complete"
Assert-Equal $script:verifyCount 0 "No verification before successful push"
$script:pushFails=$false
$script:commands=@()
$cycle=Resume-PublisherSnapshot $snapshot (Read-PublisherState $pendingPath)
Assert-Equal $cycle "2026-09-22" "Recovered cycle"
Assert-Equal $script:commands.Count 1 "Only existing commit is pushed"
Assert-Equal (Test-Path -LiteralPath $pendingPath) $false "Pending is cleared after verification"
Assert-Equal (Read-PublisherState $completedPath).dataHash "hash-a" "Completed snapshot identity"
Write-Output "PASS: failed push resumes the existing snapshot without download or duplicate commit"

Save-PublisherPending $snapshot "2026-09-22" $pendingPath
$script:unpublishedDataCommit=$false
$script:commands=@()
$script:verifyFails=$true
$caught=$false
try { Resume-PublisherSnapshot $snapshot (Read-PublisherState $pendingPath) | Out-Null } catch { $caught=$true }
Assert-Equal $caught $true "Verification failure propagates"
Assert-Equal (Test-Path -LiteralPath $pendingPath) $true "Pushed-but-unverified snapshot remains pending"
$script:verifyFails=$false
Resume-PublisherSnapshot $snapshot (Read-PublisherState $pendingPath) | Out-Null
Assert-Equal $script:commands.Count 0 "Server-accepted push is not repeated"
Write-Output "PASS: Cloudflare outage resumes verification without rebuilding or re-pushing"

$script:commands=@()
$script:unpublishedDataCommit=$true
Resume-PublisherSnapshot $snapshot $null | Out-Null
Assert-Equal $script:commands.Count 2 "Legacy pending commit is tested then pushed"
Assert-Equal $script:commands[0] @("run","test:pages") "Legacy commit validation"
Assert-Equal ($script:commands | Where-Object { $_ -contains "scripts\update_xtdata.py" }).Count 0 "Recovery never downloads new quotes"
Write-Output "PASS: pre-fix pending commits are checked before recovery"

Save-PublisherPending $snapshot "2026-09-22" $pendingPath
$script:dirtyData=$true
$script:commands=@()
$caught=$false
try { Resume-PublisherSnapshot $snapshot (Read-PublisherState $pendingPath) | Out-Null } catch { $caught=$true }
Assert-Equal $caught $true "Dirty data blocks recovery"
Assert-Equal $script:commands.Count 0 "No publication of dirty data"
$script:dirtyData=$false
$script:revertedCodeCommit=$true
$caught=$false
try { Assert-RepositoryReady -GitPath $gitPath } catch { $caught=$true; $historyError=$_.Exception.Message }
Assert-Equal $caught $true "Even reverted source-file commits block automatic push"
Assert-Equal ($historyError -like '*app/page.tsx*') $true "Rejected non-data commit is identified"
Write-Output "PASS: user changes and non-data commit history cannot be auto-published"
exit 0
