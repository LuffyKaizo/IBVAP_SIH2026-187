# start-ibvap.ps1 — Start the EXISTING IBVAP dev stack (no architecture changes).
#   FastAPI  :8000  ->  python -m uvicorn ai.main:app (cwd backend/)
#   Express  :3000  ->  cmd /c npx.cmd tsx backend/express/server.ts (cwd repo root)
# Logs: runtime-logs/ (fastapi.out.log / fastapi.err.log / bff.out.log / bff.err.log)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-ibvap.ps1 [-NoBrowser]
param(
    [int]$WaitSeconds = 150,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'SilentlyContinue'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot 'runtime-logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Python = 'C:\Program Files\Python314\python.exe'
if (-not (Test-Path $Python)) { $Python = (Get-Command python).Source }

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Test-Http([string]$uri) {
    try {
        $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200 -or $r.StatusCode -eq 401)
    } catch { return $false }
}

# --- FastAPI :8000 ---
if (Test-Port 8000) {
    Write-Host "[START] FastAPI already listening on :8000 - skipping."
} else {
    Write-Host "[START] Starting FastAPI on :8000 ..."
    Start-Process -FilePath $Python `
        -ArgumentList '-m','uvicorn','ai.main:app','--host','0.0.0.0','--port','8000' `
        -WorkingDirectory (Join-Path $ProjectRoot 'backend') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'fastapi.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'fastapi.err.log')
}

# --- Express BFF :3000 (npx.cmd, not npx.ps1) ---
if (Test-Port 3000) {
    Write-Host "[START] Express BFF already listening on :3000 - skipping."
} else {
    Write-Host "[START] Starting Express BFF on :3000 ..."
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c','npx.cmd','tsx','backend/express/server.ts' `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'bff.out.log') `
        -RedirectStandardError  (Join-Path $LogDir 'bff.err.log')
}

# --- Wait for health (FastAPI model load can take ~60-90s) ---
$fastapiOk = (Test-Port 8000)
$bffOk = (Test-Port 3000)
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline -and (-not ($fastapiOk -and $bffOk))) {
    Start-Sleep -Seconds 3
    if (-not $fastapiOk) { $fastapiOk = (Test-Http 'http://localhost:8000/docs') }
    if (-not $bffOk) { $bffOk = (Test-Http 'http://localhost:3000') }
    Write-Host ("[START] waiting... FastAPI={0} BFF={1}" -f $(if ($fastapiOk) {'UP'} else {'...'}), $(if ($bffOk) {'UP'} else {'...'}))
}

Write-Host ''
Write-Host ('[START] FastAPI :8000 -> {0}' -f $(if (Test-Http 'http://localhost:8000/docs') { 'HTTP 200' } else { 'FAILED' }))
Write-Host ('[START] Express :3000 -> {0}' -f $(if (Test-Http 'http://localhost:3000') { 'HTTP 200' } else { 'FAILED' }))
Write-Host ("[START] logs: {0}" -f $LogDir)

if (-not $fastapiOk) {
    Write-Host '[START] FastAPI FAILED - last stderr lines:'
    Get-Content (Join-Path $LogDir 'fastapi.err.log') -Tail 12
}
if (-not $bffOk) {
    Write-Host '[START] BFF FAILED - last stderr lines:'
    Get-Content (Join-Path $LogDir 'bff.err.log') -Tail 12
}

if ($fastapiOk -and $bffOk -and -not $NoBrowser) {
    Start-Process 'http://localhost:3000'
    Write-Host '[START] browser opened -> http://localhost:3000'
}
if ($fastapiOk -and $bffOk) { Write-Host '[START] IBVAP is UP.' }
else { Write-Host '[START] IBVAP is NOT fully up - see logs above.' }
