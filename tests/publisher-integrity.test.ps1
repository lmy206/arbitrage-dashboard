$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $repositoryRoot 'scripts\publisher-support.ps1')
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $repositoryRoot 'scripts\update-and-publish.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors.Message -join '; ') }
foreach ($name in @('Assert-IntegrityReport', 'Read-Utf8Text')) {
  $node = $ast.Find({param($candidate) $candidate -is [Management.Automation.Language.FunctionDefinitionAst] -and $candidate.Name -eq $name}, $true)
  if (-not $node) { throw "Missing function $name" }
  . ([scriptblock]::Create($node.Extent.Text))
}

$contract = Get-PublisherDataContract -ProjectRoot $repositoryRoot
$projectRoot = Join-Path $repositoryRoot ('.runtime\publisher-integrity-test-' + [guid]::NewGuid().ToString('N'))
$configDirectory = Join-Path $projectRoot 'config'
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
$contractPath = Join-Path $configDirectory 'dashboard-contract.json'
$reportPath = Join-Path $projectRoot 'report.json'
$outputPath = Join-Path $projectRoot 'snapshot.json'
$date = '2028-01-04'
$stamp = '2028-01-04T20:14:00+08:00'
$snapshot = [pscustomobject]@{
  dataDate = $date
  updatedAt = $stamp
  rows = @($contract.pairs | ForEach-Object { @{pair=$_} })
  sourceValidation = @{
    checks = @($contract.domesticSymbols | ForEach-Object { @{xtSymbol=$_;date=$date;status='完整'} })
    summary = @{total=$contract.domesticSymbols.Count;consistent=$contract.domesticSymbols.Count;review=0;unavailable=0}
  }
  externalSources = @($contract.externalSymbols | ForEach-Object { @{symbol=$_} })
  charts = @($contract.chartIds | ForEach-Object { @{id=$_} })
}
$report = [pscustomobject]@{
  status='ok';dataDate=$date;checkedAt=$stamp;pairCount=$contract.pairs.Count;expectedPairCount=$contract.pairs.Count
  futureDataDetected=$false;hierarchySorted=$true
}
foreach ($flag in @(
  'configurationComplete', 'indexTermHistoryComplete', 'indexTermThresholdsComplete',
  'displayedTermStructuresComplete', 'relatedObservationsComplete', 'fundingPressureOverlayComplete',
  'riskPremiumOverlaysComplete', 'imIfSpotOverlayComplete', 'imIfSpotThresholdsComplete',
  'imIcSpotOverlayComplete', 'icIfSpotOverlayComplete', 'icIfSpotThresholdsComplete',
  'growthSpotOverlayComplete', 'aluminumAlloySpreadComplete', 'spotCorrelationMetricsComplete',
  'fullDailyChartStatisticsComplete', 'domesticFreshnessComplete', 'externalRowDatesComplete', 'externalSourcesComplete'
)) { $report | Add-Member -NotePropertyName $flag -NotePropertyValue $true }
$contractJson = $contract | ConvertTo-Json -Depth 20
$snapshotJson = $snapshot | ConvertTo-Json -Depth 20
$reportJson = $report | ConvertTo-Json -Depth 20
function Reset-Fixtures {
  Write-PublisherState $contractPath ($contractJson | ConvertFrom-Json)
  Write-PublisherState $outputPath ($snapshotJson | ConvertFrom-Json)
  Write-PublisherState $reportPath ($reportJson | ConvertFrom-Json)
}
function Assert-Rejected {
  param([string]$Label)
  $rejected = $false
  try { $null = Assert-IntegrityReport } catch { $rejected = $true }
  if (-not $rejected) { throw "Expected rejection: $Label" }
}

try {
  Reset-Fixtures
  if ((Assert-IntegrityReport) -ne $date) { throw 'Valid named snapshot was rejected' }
  Write-Output 'PASS: valid snapshot uses the configured identities'

  $changedContract = Read-PublisherState $contractPath
  $changedSnapshot = Read-PublisherState $outputPath
  $changedReport = Read-PublisherState $reportPath
  $changedContract.pairs += 'fixture additional pair'
  $changedSnapshot.rows += @{pair='fixture additional pair'}
  $changedReport.pairCount++
  $changedReport.expectedPairCount++
  Write-PublisherState $contractPath $changedContract
  Write-PublisherState $outputPath $changedSnapshot
  Write-PublisherState $reportPath $changedReport
  if ((Assert-IntegrityReport) -ne $date) { throw 'Configured additional pair hit a fixed count' }
  Write-Output 'PASS: configured pair additions do not hit a fixed numeric count'

  Reset-Fixtures
  $broken = Read-PublisherState $outputPath
  $broken.rows = @($broken.rows | Select-Object -Skip 1)
  Write-PublisherState $outputPath $broken
  Assert-Rejected 'missing pair'
  Reset-Fixtures
  $broken = Read-PublisherState $outputPath
  $broken.rows[1].pair = $broken.rows[0].pair
  Write-PublisherState $outputPath $broken
  Assert-Rejected 'duplicate pair with unchanged count'
  Reset-Fixtures
  $broken = Read-PublisherState $outputPath
  $broken.sourceValidation.checks[1].xtSymbol = $broken.sourceValidation.checks[0].xtSymbol
  Write-PublisherState $outputPath $broken
  Assert-Rejected 'duplicate domestic source'
  Write-Output 'PASS: missing and duplicate identities stay blocked'

  Reset-Fixtures
  $broken = Read-PublisherState $outputPath
  $broken.externalSources[0].symbol = 'unapproved source'
  Write-PublisherState $outputPath $broken
  Assert-Rejected 'unapproved external source'
  Reset-Fixtures
  $broken = Read-PublisherState $outputPath
  $broken.sourceValidation.checks[0].date = '2028-01-03'
  Write-PublisherState $outputPath $broken
  Assert-Rejected 'stale domestic observation'
  Write-Output 'PASS: source identity and daily coverage stay blocked when invalid'

  foreach ($flag in @('configurationComplete','domesticFreshnessComplete','futureDataDetected')) {
    Reset-Fixtures
    $broken = Read-PublisherState $reportPath
    $broken.$flag = -not $broken.$flag
    Write-PublisherState $reportPath $broken
    Assert-Rejected $flag
  }
  Write-Output 'PASS: configuration, stale dates and future data still fail closed'

  Reset-Fixtures
  $broken = Read-PublisherState $reportPath
  $broken.checkedAt = '2028-01-04T20:13:00+08:00'
  Write-PublisherState $reportPath $broken
  Assert-Rejected 'same-date report from a different generation'
  Write-Output 'PASS: a prior integrity report cannot validate another snapshot'
} finally {
  foreach ($path in @($contractPath,$outputPath,$reportPath)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
  }
  Remove-Item -LiteralPath $configDirectory
  Remove-Item -LiteralPath $projectRoot
}
