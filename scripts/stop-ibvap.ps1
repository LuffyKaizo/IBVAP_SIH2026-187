# stop-ibvap.ps1 — Stop ONLY IBVAP dev services (FastAPI, Express BFF, Vite if any).
# Identifies processes by command-line markers + ancestor/port validation.
# Never kills by image name (python.exe/node.exe) or by port alone.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\stop-ibvap.ps1
$ErrorActionPreference = 'SilentlyContinue'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectName = 'SIH2026-187'
$ProjectPorts = @(3000, 8000, 5173, 4173)
$DbFile = Join-Path $ProjectRoot 'backend\ibvap.db'

# Command-line markers that prove a process belongs to IBVAP
$MarkerPattern = 'ai\.main:app|backend[/\\]express[/\\]server\.ts|vite\.config\.ts'
$SelfPattern = 'stop-ibvap|start-ibvap'

$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CommandLine
$byId = @{}
$children = @{}
foreach ($p in $all) {
    $pidKey = [int]$p.ProcessId
    $ppidKey = [int]$p.ParentProcessId
    $byId[$pidKey] = $p
    if (-not $children.ContainsKey($ppidKey)) { $children[$ppidKey] = @() }
    $children[$ppidKey] += $pidKey
}

function Test-IsIbvap($proc) {
    if (-not $proc) { return $false }
    $cl = $proc.CommandLine
    if (-not $cl) { return $false }
    if ($cl -match $SelfPattern) { return $false }
    return ($cl -match $MarkerPattern)
}

# Normalize every lookup to [int] keys
function Get-Proc([int]$procId) {
    if ($byId.ContainsKey($procId)) { return $byId[$procId] }
    return $null
}

# Build ancestor chain for a PID (closest ancestor first)
function Get-Ancestors([int]$procId) {
    $chain = @()
    $cur = Get-Proc $procId
    $guard = 0
    while ($cur -and $cur.ParentProcessId -and $guard -lt 10) {
        $par = Get-Proc ([int]$cur.ParentProcessId)
        if (-not $par) { break }
        $chain += $par
        $cur = $par
        $guard++
    }
    return $chain
}

$kill = @{}
$warnings = @()

# 1) Direct command-line matches (roots)
foreach ($p in $all) {
    if ((Test-IsIbvap $p) -and [int]$p.ProcessId -ne $PID) { $kill[[int]$p.ProcessId] = 'cmdline-match' }
}

# 2) Port owners: only if the owner or one of its ancestors matches IBVAP markers
$listening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $ProjectPorts }
foreach ($conn in $listening) {
    $ownerId = [int]$conn.OwningProcess
    if ($ownerId -eq $PID) { continue }
    $owner = Get-Proc $ownerId
    $validated = (Test-IsIbvap $owner)
    if (-not $validated) {
        foreach ($anc in Get-Ancestors $ownerId) { if (Test-IsIbvap $anc) { $validated = $true; break } }
    }
    if ($validated) {
        $kill[$ownerId] = "port-$($conn.LocalPort)-owner"
    } else {
        $warnings += "Port $($conn.LocalPort) owned by PID $ownerId ($($owner.Name)) does NOT match IBVAP markers - left untouched"
    }
}

# 3) Descendants of every matched root (process trees)
$queue = New-Object 'System.Collections.Queue'
foreach ($k in @($kill.Keys)) { $queue.Enqueue($k) }
while ($queue.Count -gt 0) {
    $id = $queue.Dequeue()
    if ($children.ContainsKey($id)) {
        foreach ($childId in $children[$id]) {
            $cid = [int]$childId
            if ($cid -ne $PID -and -not $kill.ContainsKey($cid)) {
                $child = Get-Proc $cid
                if ($child -and $child.CommandLine -and $child.CommandLine -notmatch $SelfPattern) {
                    $kill[$cid] = "descendant-of-$id"
                    $queue.Enqueue($cid)
                }
            }
        }
    }
}

if ($kill.Count -eq 0) {
    Write-Host "[STOP] No IBVAP processes found - nothing to stop."
} else {
    Write-Host "[STOP] IBVAP processes identified:"
    foreach ($k in ($kill.Keys | Sort-Object)) {
        $p = Get-Proc $k
        $nm = if ($p -and $p.Name) { $p.Name } else { '?' }
        Write-Host ("  PID {0} [{1}] ({2})" -f $k, $nm, $kill[$k])
    }
    foreach ($k in $kill.Keys) {
        Stop-Process -Id $k -Force -ErrorAction SilentlyContinue
    }
}

# Wait for termination (up to 10s)
$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 500
    $stillAlive = @()
    foreach ($k in $kill.Keys) {
        if (Get-Process -Id $k -ErrorAction SilentlyContinue) { $stillAlive += $k }
    }
} while ($stillAlive.Count -gt 0 -and (Get-Date) -lt $deadline)
if ($stillAlive.Count -gt 0) {
    Write-Host "[STOP] WARNING: still alive after 10s: $($stillAlive -join ', ')"
} elseif ($kill.Count -gt 0) {
    Write-Host "[STOP] All identified IBVAP processes terminated."
}

# Verify project ports are closed (unrelated owners untouched)
foreach ($port in $ProjectPorts) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "[STOP] port ${port}: STILL LISTENING (PID $($c[0].OwningProcess))" }
    else { Write-Host "[STOP] port ${port}: closed" }
}
foreach ($w in $warnings) { Write-Host "[STOP] NOTE: $w" }

# Verify SQLite lock released
if (Test-Path $DbFile) {
    try {
        $fs = [System.IO.File]::Open($DbFile, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $fs.Close()
        Write-Host "[STOP] database lock released ($DbFile)"
    } catch {
        Write-Host "[STOP] database still LOCKED: $($_.Exception.Message)"
    }
}
Write-Host "[STOP] done."
