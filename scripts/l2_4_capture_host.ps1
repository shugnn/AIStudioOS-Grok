#Requires -Version 5.1
<#
.SYNOPSIS
  Read-only L2-4 evidence capture for the founder Windows host.

.DESCRIPTION
  Writes docs/progress/l2_4/host/capture.json (or -OutDir) with evidence_class
  host_capture. Inventory only: scheduled task snapshot, Application Error 1000
  histogram, Windows Terminal fault timestamps, reboot/shutdown events, Task
  Scheduler operational starts, and runner-*.json timestamps.

  Does not register tasks, change task state, or delete tasks.
  Does not decide L2-4 PASS. Does not claim production 7x24.

.PARAMETER Since
  UTC window start, ISO-8601. Default 2026-11-03T00:00:00Z (duty start day).

.PARAMETER Until
  UTC window end, ISO-8601. Default: now.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\l2_4_capture_host.ps1 `
    -OutDir .\docs\progress\l2_4\host `
    -Since "2026-11-03T00:00:00Z" `
    -Until "2026-11-06T00:00:00Z"
#>
[CmdletBinding()]
param(
    [string]$OutDir = "docs\progress\l2_4\host",
    [string]$Since = "2026-11-03T00:00:00Z",
    [string]$Until = "",
    [string[]]$TaskNames = @("AIStudioOS-Grok-L1", "AIStudioOS-Grok-Watchdog"),
    [int]$WindowSeconds = 600,
    [int]$MaxListed = 2000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Convert-ToUtcDateTime([string]$Iso) {
    $dto = [datetimeoffset]::Parse(
        $Iso,
        [cultureinfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::RoundtripKind
    )
    return $dto.UtcDateTime
}

function Format-UtcIso([datetime]$Value) {
    $utc = $Value
    if ($Value.Kind -eq [datetimekind]::Unspecified) {
        $utc = [datetime]::SpecifyKind($Value, [datetimekind]::Local).ToUniversalTime()
    } elseif ($Value.Kind -eq [datetimekind]::Local) {
        $utc = $Value.ToUniversalTime()
    }
    return $utc.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function Test-RealTime([object]$Value) {
    if ($null -eq $Value) { return $false }
    if ($Value -isnot [datetime]) { return $false }
    if ($Value.Year -lt 2000) { return $false }
    return $true
}

function Escape-JsonString([string]$Text) {
    if ($null -eq $Text) { return "null" }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        switch ($code) {
            34 { [void]$sb.Append('\"'); break }
            92 { [void]$sb.Append('\\'); break }
            8 { [void]$sb.Append('\b'); break }
            12 { [void]$sb.Append('\f'); break }
            10 { [void]$sb.Append('\n'); break }
            13 { [void]$sb.Append('\r'); break }
            9 { [void]$sb.Append('\t'); break }
            default {
                if ($code -lt 32) {
                    [void]$sb.Append(('\u{0:x4}' -f $code))
                } else {
                    [void]$sb.Append($ch)
                }
            }
        }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function ConvertTo-CaptureJson([object]$Value) {
    if ($null -eq $Value) { return "null" }
    if ($Value -is [string]) { return (Escape-JsonString $Value) }
    if ($Value -is [bool]) { if ($Value) { return "true" } else { return "false" } }
    if ($Value -is [datetime]) { return (Escape-JsonString (Format-UtcIso $Value)) }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [decimal] -or $Value -is [double] -or $Value -is [float]) {
        return ([string]$Value).Replace(",", ".")
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $pairs = New-Object System.Collections.Generic.List[string]
        foreach ($key in $Value.Keys) {
            $pairs.Add(((Escape-JsonString ([string]$key)) + ":" + (ConvertTo-CaptureJson $Value[$key])))
        }
        return "{" + ($pairs -join ",") + "}"
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $items = New-Object System.Collections.Generic.List[string]
        foreach ($item in $Value) {
            $items.Add((ConvertTo-CaptureJson $item))
        }
        return "[" + ($items -join ",") + "]"
    }
    return (Escape-JsonString ([string]$Value))
}

function Get-EventPropertyMap([System.Diagnostics.Eventing.Reader.EventRecord]$Event) {
    $map = @{}
    try {
        $xml = [xml]$Event.ToXml()
    } catch {
        return $map
    }
    $nodes = $xml.Event.EventData.Data
    if ($null -eq $nodes) { return $map }
    foreach ($node in @($nodes)) {
        $name = [string]$node.Name
        if ([string]::IsNullOrEmpty($name)) { continue }
        $map[$name] = [string]$node.InnerText
    }
    return $map
}

function Get-FaultingApplication([System.Diagnostics.Eventing.Reader.EventRecord]$Event, $Props) {
    foreach ($key in @("AppName", "FaultingApplication", "Application")) {
        if ($Props.ContainsKey($key) -and -not [string]::IsNullOrWhiteSpace($Props[$key])) {
            return [string]$Props[$key]
        }
    }
    $message = ""
    try { $message = [string]$Event.Message } catch { $message = "" }
    $match = [regex]::Match($message, "Faulting application name:\s*([^,\r\n]+)")
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return ""
}

function Get-PathLeaf([string]$PathText) {
    if ([string]::IsNullOrWhiteSpace($PathText)) { return "" }
    $norm = $PathText.Replace("/", "\")
    $idx = $norm.LastIndexOf("\")
    if ($idx -ge 0 -and $idx -lt ($norm.Length - 1)) {
        return $norm.Substring($idx + 1)
    }
    return $norm.Trim("\")
}

function Test-WindowsTerminalApp([string]$App) {
    if ([string]::IsNullOrWhiteSpace($App)) { return $false }
    $leaf = $App.Trim()
    return [regex]::IsMatch($leaf, '(?i)(^|[\\/])(WindowsTerminal|wt)\.exe$')
}

function Get-WinEventsSafe($Filter, [string]$Label) {
    $result = [ordered]@{
        available = $true
        error     = $null
        events    = @()
    }
    try {
        $events = @(Get-WinEvent -FilterHashtable $Filter -ErrorAction Stop)
        $result.events = $events
    } catch {
        $msg = "$_"
        # EN + zh-CN empty-result messages from Get-WinEvent
        if ($msg -match "No events were found|找不到任何与指定的选择条件匹配的事件") {
            $result.events = @()
        } else {
            $result.available = $false
            $result.error = "${Label}: $msg"
            $result.events = @()
        }
    }
    return $result
}

$sinceUtc = Convert-ToUtcDateTime $Since
if ([string]::IsNullOrWhiteSpace($Until)) {
    $untilUtc = [datetime]::UtcNow
} else {
    $untilUtc = Convert-ToUtcDateTime $Until
}
$sinceLocal = [datetime]::SpecifyKind($sinceUtc, [datetimekind]::Utc).ToLocalTime()
$untilLocal = [datetime]::SpecifyKind($untilUtc, [datetimekind]::Utc).ToLocalTime()

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
if (-not [System.IO.Path]::IsPathRooted($OutDir)) {
    $OutDir = Join-Path $repoRoot $OutDir
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$gitSha = "unknown"
try {
    $gitSha = (& git rev-parse HEAD).Trim()
    if ([string]::IsNullOrWhiteSpace($gitSha)) { $gitSha = "unknown" }
} catch {
    $gitSha = "unknown"
}

$taskSnapshots = New-Object System.Collections.Generic.List[object]
foreach ($taskName in $TaskNames) {
    $row = [ordered]@{
        task_name        = $taskName
        present          = $false
        state            = $null
        last_run_time    = $null
        next_run_time    = $null
        last_task_result = $null
        number_of_missed_runs = $null
        logon_type       = $null
        run_level        = $null
        user_id          = $null
        actions          = @()
        error            = $null
    }
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -InputObject $task
        $row.present = $true
        $row.state = [string]$task.State
        if (Test-RealTime $info.LastRunTime) { $row.last_run_time = (Format-UtcIso $info.LastRunTime) }
        if (Test-RealTime $info.NextRunTime) { $row.next_run_time = (Format-UtcIso $info.NextRunTime) }
        $row.last_task_result = [int]$info.LastTaskResult
        $row.number_of_missed_runs = [int]$info.NumberOfMissedRuns
        if ($task.Principal) {
            $row.logon_type = [string]$task.Principal.LogonType
            $row.run_level = [string]$task.Principal.RunLevel
            $row.user_id = [string]$task.Principal.UserId
        }
        $actions = New-Object System.Collections.Generic.List[object]
        foreach ($action in @($task.Actions)) {
            if ($null -eq $action) { continue }
            $actions.Add([ordered]@{
                    execute            = [string]$action.Execute
                    arguments          = [string]$action.Arguments
                    working_directory  = [string]$action.WorkingDirectory
                })
        }
        $row.actions = $actions
    } catch {
        $row.error = "$_"
    }
    $taskSnapshots.Add($row)
}

$appQuery = Get-WinEventsSafe @{
    LogName   = "Application"
    ProviderName = "Application Error"
    Id        = 1000
    StartTime = $sinceLocal
    EndTime   = $untilLocal
} "Application Error 1000"

$byApp = @{}
$wtErrors = New-Object System.Collections.Generic.List[object]
$appTruncated = $false
$seen = 0
foreach ($ev in @($appQuery.events)) {
    $seen++
    $props = Get-EventPropertyMap $ev
    $app = Get-FaultingApplication $ev $props
    $leaf = Get-PathLeaf $app
    $key = if ([string]::IsNullOrWhiteSpace($leaf)) { "(unknown)" } else { $leaf }
    if ($byApp.ContainsKey($key)) { $byApp[$key]++ } else { $byApp[$key] = 1 }
    if (Test-WindowsTerminalApp $app) {
        if ($wtErrors.Count -ge $MaxListed) {
            $appTruncated = $true
            continue
        }
        $moduleName = ""
        if ($props.ContainsKey("ModuleName")) { $moduleName = [string]$props["ModuleName"] }
        $exceptionCode = ""
        if ($props.ContainsKey("ExceptionCode")) { $exceptionCode = [string]$props["ExceptionCode"] }
        $wtErrors.Add([ordered]@{
                utc                  = (Format-UtcIso $ev.TimeCreated)
                event_id             = 1000
                provider             = "Application Error"
                faulting_application = $app
                faulting_module      = $moduleName
                exception_code       = $exceptionCode
                record_id            = [int64]$ev.RecordId
            })
    }
}

$histogram = New-Object System.Collections.Generic.List[object]
foreach ($key in ($byApp.Keys | Sort-Object)) {
    $histogram.Add([ordered]@{ name = [string]$key; count = [int]$byApp[$key] })
}

$rebootSpecs = @(
    @{ Log = "System"; Provider = "User32"; Id = 1074; Kind = "planned_shutdown" },
    @{ Log = "System"; Provider = "EventLog"; Id = 6008; Kind = "unexpected_shutdown" },
    @{ Log = "System"; Provider = "Microsoft-Windows-Kernel-Power"; Id = 41; Kind = "kernel_power" },
    @{ Log = "System"; Provider = "EventLog"; Id = 6005; Kind = "event_log_start" },
    @{ Log = "System"; Provider = "EventLog"; Id = 6006; Kind = "event_log_stop" },
    @{ Log = "System"; Provider = "Microsoft-Windows-Kernel-General"; Id = 12; Kind = "kernel_general_start" }
)
$reboots = New-Object System.Collections.Generic.List[object]
$rebootErrors = New-Object System.Collections.Generic.List[string]
foreach ($spec in $rebootSpecs) {
    $q = Get-WinEventsSafe @{
        LogName      = $spec.Log
        ProviderName = $spec.Provider
        Id           = $spec.Id
        StartTime    = $sinceLocal
        EndTime      = $untilLocal
    } $spec.Kind
    if (-not $q.available -and $q.error) { $rebootErrors.Add([string]$q.error) }
    foreach ($ev in @($q.events)) {
        $detail = ""
        try { $detail = ([string]$ev.Message) } catch { $detail = "" }
        if ($detail.Length -gt 500) { $detail = $detail.Substring(0, 500) }
        $reboots.Add([ordered]@{
                utc      = (Format-UtcIso $ev.TimeCreated)
                event_id = [int]$spec.Id
                kind     = [string]$spec.Kind
                provider = [string]$spec.Provider
                record_id = [int64]$ev.RecordId
                detail   = $detail
            })
    }
}

$taskHistory = [ordered]@{
    available = $true
    error     = $null
    runs      = @()
}
$taskRuns = New-Object System.Collections.Generic.List[object]
$history = Get-WinEventsSafe @{
    LogName   = "Microsoft-Windows-TaskScheduler/Operational"
    Id        = 200
    StartTime = $sinceLocal
    EndTime   = $untilLocal
} "TaskScheduler 200"
$taskHistory.available = [bool]$history.available
$taskHistory.error = $history.error
$wanted = @{}
foreach ($taskName in $TaskNames) { $wanted[$taskName.ToLowerInvariant()] = $true }
foreach ($ev in @($history.events)) {
    if ($taskRuns.Count -ge $MaxListed) { break }
    $props = Get-EventPropertyMap $ev
    $rawName = ""
    if ($props.ContainsKey("TaskName")) { $rawName = [string]$props["TaskName"] }
    $leaf = Get-PathLeaf $rawName
    if (-not $wanted.ContainsKey($leaf.ToLowerInvariant())) { continue }
    $taskRuns.Add([ordered]@{
            utc       = (Format-UtcIso $ev.TimeCreated)
            task_name = $leaf
            event_id  = 200
            record_id = [int64]$ev.RecordId
        })
}
$taskHistory.runs = $taskRuns

$runnerArtifacts = New-Object System.Collections.Generic.List[object]
$progress = Join-Path $repoRoot "docs\progress"
if (Test-Path $progress) {
    $files = @(Get-ChildItem -Path $progress -Filter "runner-*.json" -File -ErrorAction SilentlyContinue)
    foreach ($file in $files) {
        if ($runnerArtifacts.Count -ge $MaxListed) { break }
        $utc = $null
        try {
            $parsed = Get-Content -Raw -Path $file.FullName | ConvertFrom-Json
            if ($parsed.utc) {
                $utc = (Format-UtcIso (Convert-ToUtcDateTime ([string]$parsed.utc)))
            }
        } catch {
            $utc = $null
        }
        if ($null -eq $utc) { $utc = (Format-UtcIso $file.LastWriteTimeUtc) }
        $stamp = Convert-ToUtcDateTime $utc
        if ($stamp -lt $sinceUtc -or $stamp -gt $untilUtc) { continue }
        $runnerArtifacts.Add([ordered]@{
                name   = $file.Name
                utc    = $utc
                source = "runner_json_utc_or_mtime"
            })
    }
}

$processTree = [ordered]@{
    available = $false
    links     = @()
    reason    = "not_collected_by_this_script"
}

$capture = [ordered]@{
    schema          = "aistudioos-grok.l2-4.capture.v1"
    evidence_class  = "host_capture"
    synthetic       = $false
    note            = "Read-only host capture. Not an L2-4 PASS. Not a production 7x24 claim."
    captured_utc    = (Format-UtcIso ([datetime]::UtcNow))
    host            = [string]$env:COMPUTERNAME
    git_sha         = $gitSha
    window_seconds  = $WindowSeconds
    since_utc       = (Format-UtcIso $sinceUtc)
    until_utc       = (Format-UtcIso $untilUtc)
    collector       = "scripts/l2_4_capture_host.ps1"
    collector_mode  = "read_only"
    tasks           = $taskSnapshots
    task_runs       = $taskRuns.ToArray()
    task_history    = $taskHistory
    runner_artifacts = $runnerArtifacts.ToArray()
    wt_errors       = $wtErrors.ToArray()
    reboots         = $reboots.ToArray()
    reboot_query_errors = $rebootErrors.ToArray()
    application_error_1000 = [ordered]@{
        total_in_window          = [int]$seen
        truncated                = [bool]$appTruncated
        query_available          = [bool]$appQuery.available
        query_error              = $appQuery.error
        by_faulting_application  = $histogram.ToArray()
    }
    process_tree    = $processTree
    supervision_watch_target = $null
}

$outFile = Join-Path $OutDir "capture.json"
$json = ConvertTo-CaptureJson $capture
[System.IO.File]::WriteAllText($outFile, $json + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Output ("wrote " + $outFile + " wt_errors=" + $wtErrors.Count + " reboots=" + $reboots.Count + " task_runs=" + $taskRuns.Count)
