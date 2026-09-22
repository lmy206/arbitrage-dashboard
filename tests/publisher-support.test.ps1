$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $PSScriptRoot) "scripts\publisher-support.ps1")
function Assert-Equal {
  param($Actual, $Expected, [string]$Label)
  if (($Actual -join ",") -ne ($Expected -join ",")) { throw "$Label mismatch: $Actual / $Expected" }
}
function Write-PublishLog { param([string]$Message) }

Assert-Equal (Get-PublisherCycleDate ([datetime]"2026-09-23 04:55")) "2026-09-22" "After midnight belongs to prior evening"
Assert-Equal (Get-PublisherCycleDate ([datetime]"2026-09-23 20:09")) "2026-09-22" "Before today's update"
Assert-Equal (Get-PublisherCycleDate ([datetime]"2026-09-23 20:10")) "2026-09-23" "New daily cycle"
Assert-Equal (Get-PublisherCycleDate ([datetime]"2026-09-21 09:00")) "2026-09-18" "Monday morning belongs to Friday"
$done = [pscustomobject]@{cycleDate="2026-09-22"}
Assert-Equal (Test-PublisherScheduledWork "2026-09-22" $done $null $false) $false "Finished cycle does not redownload"
Assert-Equal (Test-PublisherScheduledWork "2026-09-22" $done $null $true) $true "Pending publication takes priority"
Assert-Equal (Test-PublisherScheduledWork "2026-09-23" $done $null $false) $true "New day runs normally"
$blocked = [pscustomobject]@{status="failed";cycleDate="2026-09-22";retryable=$false}
Assert-Equal (Test-PublisherScheduledWork "2026-09-22" $null $blocked $true) $false "Permanent failure requires attention"
$transient = [pscustomobject]@{status="failed";cycleDate="2026-09-22";retryable=$true}
Assert-Equal (Test-PublisherScheduledWork "2026-09-22" $null $transient $true) $true "Network failure remains recoverable"
Write-Output "PASS: evening, midnight, weekend and completed-cycle scheduling"

Assert-Equal (Get-WindowsPublisherProxy @{ProxyEnable=1;ProxyServer="127.0.0.1:7890"}) "http://127.0.0.1:7890" "Windows local proxy"
Assert-Equal (Get-WindowsPublisherProxy @{ProxyEnable=1;ProxyServer="http=127.0.0.1:8000;https=127.0.0.1:7890"}) "http://127.0.0.1:7890" "HTTPS-specific proxy"
Assert-Equal (Get-WindowsPublisherProxy @{ProxyEnable=0;ProxyServer="127.0.0.1:7890"}) $null "Disabled proxy"
Assert-Equal (Get-WindowsPublisherProxy @{ProxyEnable=1;AutoConfigURL="https://example.com/proxy.pac"}) $null "PAC is not guessed"
foreach ($address in @("https://example.com:7890", "http://user:example@127.0.0.1:7890", "http://127.0.0.1:7890/path", "http://127.0.0.1:7890/?x=1")) {
  Assert-Equal (Get-WindowsPublisherProxy @{ProxyEnable=1;ProxyServer=$address}) $null "Unapproved proxy form is not imported"
}
function Get-ItemProperty { param([string]$LiteralPath, [string]$ErrorAction) return @{ProxyEnable=1;ProxyServer="127.0.0.1:7890"} }
$script:publisherExplicitProxy = $false
Assert-Equal ((@(Get-PublisherGitNetworkOptions) -contains "http.proxy=http://127.0.0.1:7890")) $true "Windows proxy is scoped to Git command"
$script:publisherExplicitProxy = $true
Assert-Equal ((@(Get-PublisherGitNetworkOptions) -contains "http.proxy=http://127.0.0.1:7890")) $false "Explicit Git/environment proxy wins"
Write-Output "PASS: existing local proxy is reused without altering explicit proxy or TLS policy"

$snapshot = [pscustomobject]@{commit="abc123";dataHash="hash-a";dataDate="2026-09-22";updatedAt="2026-09-22T20:13:57+08:00"}
$pending = [pscustomobject]@{commit="abc123";dataHash="hash-a";dataDate="2026-09-22";updatedAt="2026-09-22T20:13:57+08:00"}
Assert-PublisherPendingSnapshot $pending $snapshot
$pending.dataHash = "hash-b"
$caught = $false
try { Assert-PublisherPendingSnapshot $pending $snapshot } catch { $caught = $true }
Assert-Equal $caught $true "Changed data cannot reuse a pending publication receipt"
Write-Output "PASS: pending publication checks data identity"
exit 0
