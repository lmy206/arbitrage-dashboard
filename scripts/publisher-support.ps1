# Shared by the scheduled publisher, installer, and local regression checks.

function Get-PublisherCycleDate {
  param([datetime]$Now = (Get-Date))
  $cycle = $Now.Date
  if ($Now -lt $cycle.AddHours(20).AddMinutes(10)) { $cycle = $cycle.AddDays(-1) }
  while ($cycle.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    $cycle = $cycle.AddDays(-1)
  }
  return $cycle.ToString("yyyy-MM-dd")
}

function Read-PublisherState {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return ([IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json)
}

function Write-PublisherState {
  param([string]$Path, [object]$Value)
  $temporaryPath = "$Path.tmp"
  [IO.File]::WriteAllText($temporaryPath, ($Value | ConvertTo-Json -Depth 12), (New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Test-PublisherScheduledWork {
  param([string]$CycleDate, [object]$Completed, [object]$LastStatus, [bool]$HasPending)
  if ($LastStatus -and $LastStatus.status -eq "failed" -and
      $LastStatus.cycleDate -eq $CycleDate -and $LastStatus.retryable -eq $false) {
    return $false
  }
  if ($HasPending) { return $true }
  return -not ($Completed -and $Completed.cycleDate -ge $CycleDate)
}

function Get-WindowsPublisherProxy {
  param([object]$Settings)
  if (-not $Settings -or $Settings.ProxyEnable -ne 1 -or -not $Settings.ProxyServer) { return $null }
  $server = [string]$Settings.ProxyServer
  if ($server.Contains("=")) {
    $proxyMap = @{}
    foreach ($part in $server.Split(";")) {
      $pieces = $part.Split("=", 2)
      if ($pieces.Length -eq 2) { $proxyMap[$pieces[0].Trim().ToLowerInvariant()] = $pieces[1].Trim() }
    }
    $server = if ($proxyMap.ContainsKey("https")) { $proxyMap["https"] } else { $proxyMap["http"] }
  }
  if (-not $server) { return $null }
  if ($server -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $server = "http://$server" }
  $proxyUri = $null
  if (-not [Uri]::TryCreate($server, [UriKind]::Absolute, [ref]$proxyUri)) { return $null }
  # Only reuse the user's existing local proxy, never invent a remote relay.
  if (-not $proxyUri.IsLoopback -or $proxyUri.Scheme -notin @("http", "https", "socks5", "socks5h") -or
      $proxyUri.UserInfo -or $proxyUri.Query -or $proxyUri.Fragment -or $proxyUri.AbsolutePath -notin @("", "/") -or
      $proxyUri.Port -le 0) { return $null }
  return $proxyUri.GetLeftPart([UriPartial]::Authority)
}

function Initialize-PublisherNetwork {
  param([string]$GitPath, [string]$ProjectRoot)
  $script:publisherExplicitProxy = [bool]($env:HTTPS_PROXY -or $env:HTTP_PROXY -or $env:ALL_PROXY)
  if (-not $script:publisherExplicitProxy) {
    $origin = @(& $GitPath -C $ProjectRoot remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or $origin.Count -ne 1) { throw "无法读取发布仓库 origin" }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
      $configuredProxy = @(& $GitPath -C $ProjectRoot config --get-urlmatch http.proxy $origin[0] 2>$null)
      $proxyConfigExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($proxyConfigExit -notin @(0, 1)) { throw "无法核验 Git 代理配置" }
    # An explicitly configured empty value also counts: it requests a direct connection.
    $script:publisherExplicitProxy = $proxyConfigExit -eq 0
  }
  $script:publisherLastRoute = $null
}

function Get-PublisherGitNetworkOptions {
  [string[]]$options = @("-c", "http.version=HTTP/1.1", "-c", "http.lowSpeedLimit=1", "-c", "http.lowSpeedTime=45")
  $route = "Git 已有配置/环境"
  if (-not $script:publisherExplicitProxy) {
    $settings = Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
    $proxy = Get-WindowsPublisherProxy -Settings $settings
    if ($proxy) {
      $options += @("-c", "http.proxy=$proxy")
      $route = "Windows 已启用的本机代理 $proxy"
    } else { $route = "直连（未发现已启用的本机代理）" }
  }
  if ($route -ne $script:publisherLastRoute) {
    Write-PublishLog "Git 连接方式：$route"
    $script:publisherLastRoute = $route
  }
  return $options
}

function Get-PublisherHeadSnapshot {
  param([string]$GitPath, [string]$ProjectRoot)
  $json = @(& $GitPath -C $ProjectRoot show "HEAD:app/data/arbitrage.json") -join "`n"
  if ($LASTEXITCODE -ne 0) { throw "无法读取已提交的看板快照" }
  $commit = @(& $GitPath -C $ProjectRoot rev-parse HEAD) -join ""
  if ($LASTEXITCODE -ne 0) { throw "无法读取看板提交号" }
  $dataDate = Get-JsonDataDate -JsonText $json
  $updatedAt = Get-JsonUpdatedAt -JsonText $json
  return [pscustomobject]@{
    json = $json
    commit = $commit.Trim()
    dataDate = $dataDate
    updatedAt = $updatedAt
    dataHash = Get-NormalizedJsonHash -JsonText $json
    cycleDate = Get-PublisherCycleDate -Now ([DateTimeOffset]::Parse($updatedAt).LocalDateTime)
  }
}

function Assert-PublisherPendingSnapshot {
  param([object]$Pending, [object]$Snapshot)
  if ($Pending.dataHash -ne $Snapshot.dataHash -or $Pending.updatedAt -ne $Snapshot.updatedAt -or
      $Pending.dataDate -ne $Snapshot.dataDate) {
    throw "待发布记录与当前已提交快照不一致，停止自动恢复"
  }
}

function Save-PublisherPending {
  param([object]$Snapshot, [string]$CycleDate, [string]$Path)
  Write-PublisherState -Path $Path -Value ([ordered]@{
    schemaVersion = 1
    commit = $Snapshot.commit
    dataHash = $Snapshot.dataHash
    dataDate = $Snapshot.dataDate
    updatedAt = $Snapshot.updatedAt
    cycleDate = $CycleDate
    validatedAt = (Get-Date).ToString("o")
  })
}

function Save-PublisherCompletion {
  param([object]$Snapshot, [string]$CycleDate, [string]$CompletedPath, [string]$PendingPath)
  Write-PublisherState -Path $CompletedPath -Value ([ordered]@{
    cycleDate = $CycleDate
    commit = $Snapshot.commit
    dataHash = $Snapshot.dataHash
    dataDate = $Snapshot.dataDate
    updatedAt = $Snapshot.updatedAt
    confirmedAt = (Get-Date).ToString("o")
  })
  if (Test-Path -LiteralPath $PendingPath) { Remove-Item -LiteralPath $PendingPath }
}
