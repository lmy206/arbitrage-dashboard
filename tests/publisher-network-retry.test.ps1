$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  (Join-Path $projectRoot "scripts\update-and-publish.ps1"), [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors) { throw ($parseErrors.Message -join "; ") }
$definition = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "Invoke-LoggedCommand" }, $true)
if (-not $definition) { throw "Missing retry function" }
. ([scriptblock]::Create($definition.Extent.Text))

$runtimeDirectory = Join-Path $projectRoot ".runtime"
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$logPath = Join-Path $runtimeDirectory "publisher-network-retry-test.log"
function Write-PublishLog { param([string]$Message) }
function Start-Sleep { param([int]$Seconds) $script:delays += $Seconds }
function Invoke-FakeGit {
  $script:invocations += ,@($args)
  $index = [Math]::Min($script:attempts, $script:responses.Count - 1)
  $script:attempts++
  $global:LASTEXITCODE = $script:responses[$index].Code
  Write-Output $script:responses[$index].Text
}
function Reset-FakeGit {
  param([object[]]$Responses)
  $script:responses = $Responses
  $script:attempts = 0
  $script:delays = @()
  $script:invocations = @()
}
function Assert-Equal {
  param($Actual, $Expected, [string]$Label)
  if (($Actual -join ",") -ne ($Expected -join ",")) { throw "$Label mismatch: $Actual / $Expected" }
}

Reset-FakeGit @(@{Code=128;Text="fatal: Recv failure: Connection was reset"}, @{Code=128;Text="fatal: HTTP 503"}, @{Code=0;Text="updated"})
$result = Invoke-LoggedCommand -FilePath "Invoke-FakeGit" -ArgumentList @("fetch", "origin", "main") -Step "test fetch" -RetryGitNetwork
Assert-Equal $result "updated" "Recovered output"
Assert-Equal $script:attempts 3 "Recovery attempts"
Assert-Equal $script:delays @(5,10) "Backoff"
Assert-Equal $script:invocations[0] @("-c","http.version=HTTP/1.1","-c","http.lowSpeedLimit=1","-c","http.lowSpeedTime=45","fetch","origin","main") "Scoped Git transport options"
Write-Output "PASS: transient failures recover with bounded backoff"

Reset-FakeGit @(@{Code=128;Text="fatal: Connection was reset"})
$caught = $false
try { Invoke-LoggedCommand -FilePath "Invoke-FakeGit" -ArgumentList @("push","origin","HEAD:main") -Step "test push" -RetryGitNetwork | Out-Null } catch { $caught = $true }
Assert-Equal $caught $true "Exhaustion propagates failure"
Assert-Equal $script:attempts 4 "Attempt limit"
Assert-Equal $script:delays @(5,10,20) "Exhaustion delays"
Write-Output "PASS: persistent transport failure stops after four attempts"

foreach ($failure in @("fatal: Authentication failed", "fatal: SSL certificate problem; Connection was reset", "! [rejected] main -> main (fetch first)")) {
  Reset-FakeGit @(@{Code=128;Text=$failure})
  $caught = $false
  try { Invoke-LoggedCommand -FilePath "Invoke-FakeGit" -ArgumentList @("push","origin","main") -Step "permanent failure" -RetryGitNetwork | Out-Null } catch { $caught = $true }
  Assert-Equal $caught $true "Permanent error propagates"
  Assert-Equal $script:attempts 1 "Permanent errors are not retried"
  Assert-Equal $script:delays @() "Permanent errors do not sleep"
}
Write-Output "PASS: auth, TLS certificate and divergent-history failures stop immediately"

Reset-FakeGit @(@{Code=1;Text="Connection was reset"})
$caught = $false
try { Invoke-LoggedCommand -FilePath "Invoke-FakeGit" -ArgumentList @("run","test:pages") -Step "build failure" | Out-Null } catch { $caught = $true }
Assert-Equal $caught $true "Non-network command failure propagates"
Assert-Equal $script:attempts 1 "No opt-in means no retry"
Assert-Equal $script:invocations[0] @("run","test:pages") "Other commands are unchanged"
Write-Output "PASS: data, build and commit commands keep single-execution behavior"

Reset-FakeGit @(@{Code=0;Text="data updated"})
$result = Invoke-LoggedCommand -FilePath "Invoke-FakeGit" -ArgumentList @("scripts\update_xtdata.py") -Step "single script argument"
Assert-Equal $result "data updated" "Single-argument output"
Assert-Equal $script:invocations[0].Count 1 "Single argument stays an array"
Assert-Equal $script:invocations[0][0] "scripts\update_xtdata.py" "Script path is not split into characters"
Write-Output "PASS: Windows PowerShell preserves a single Python script argument"
exit 0
