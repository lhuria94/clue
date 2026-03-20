# ─────────────────────────────────────────────────────────────
# clue bootstrap for Windows (PowerShell)
#
# Usage:
#   git clone <repo-url>; cd clue; .\setup.ps1
#
# If you get a "running scripts is disabled" error, run:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# ─────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"

function Write-Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }
function Write-Step($msg) { Write-Host "`n-- $msg" -ForegroundColor White }

Write-Host "`nclue — AI efficiency scoring for Claude Code" -ForegroundColor White
Write-Host ("=" * 55)

# ── Step 1: Find Python 3.10+ ─────────────────────────────────
Write-Step "Python"

$Python = $null
foreach ($cmd in @("python3", "python", "py -3")) {
    try {
        $ver = & $cmd.Split()[0] $cmd.Split()[1..99] -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                $Python = $cmd
                break
            }
        }
    } catch { }
}

if (-not $Python) {
    Write-Fail "Python 3.10+ not found"
    Write-Host ""
    Write-Host "  Install Python:"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host "    or: https://python.org/downloads/"
    Write-Host ""
    Write-Host "  Make sure to check 'Add to PATH' during install."
    exit 1
}

$PythonVer = & $Python.Split()[0] $Python.Split()[1..99] --version
Write-Ok "Found $PythonVer"

# ── Step 2: Virtual environment ────────────────────────────────
Write-Step "Virtual Environment"

$Venv = ".venv"
if (-not (Test-Path $Venv)) {
    Write-Host "  [..]   Creating virtual environment..." -ForegroundColor Cyan
    & $Python.Split()[0] $Python.Split()[1..99] -m venv $Venv
    Write-Ok "Created $Venv\"
} else {
    Write-Ok "Already exists"
}

$VenvPython = (Resolve-Path (Join-Path $Venv "Scripts\python.exe")).Path
$VenvPip = (Resolve-Path (Join-Path $Venv "Scripts\pip.exe")).Path

# ── Step 3: Install ───────────────────────────────────────────
Write-Step "Install"

& $VenvPip install --quiet -e ".[test,dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install failed — check your network connection and try again"
    exit 1
}
Write-Ok "Installed clue"

# ── Step 4: Claude Code data ──────────────────────────────────
Write-Step "Claude Code Data"

$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
if (Test-Path $ClaudeDir) {
    Write-Ok "Found $ClaudeDir"
    $HistoryFile = Join-Path $ClaudeDir "history.jsonl"
    if (Test-Path $HistoryFile) {
        $lines = (Get-Content $HistoryFile | Measure-Object -Line).Lines
        Write-Ok "history.jsonl: $lines prompts"
    }
} else {
    Write-Warn "~/.claude/ not found — install Claude Code first"
    Write-Host "    npm install -g @anthropic-ai/claude-code"
}

# ── Step 5: Tests ─────────────────────────────────────────────
Write-Step "Tests"

$TestExe = Join-Path $Venv "Scripts\pytest.exe"
& $TestExe tests/ -q --tb=line 2>&1 | Select-Object -Last 1 | ForEach-Object { Write-Ok $_ }

# ── Step 6: Setup ─────────────────────────────────────────────
Write-Step "Setup"

if (Test-Path (Join-Path $ClaudeDir "history.jsonl")) {
    & $VenvPython -m clue setup
} else {
    Write-Warn "Skipping setup — no Claude Code data yet"
    Write-Host "    After using Claude Code, run: $VenvPython -m clue setup"
}

# ── Step 7: Doctor ────────────────────────────────────────────
Write-Step "Doctor"

try { & $VenvPython -m clue doctor } catch { }

# ── Summary ───────────────────────────────────────────────────
Write-Host ""
Write-Host ("=" * 55)
Write-Host "Ready! Commands:" -ForegroundColor White
Write-Host ""
Write-Host "  $VenvPython -m clue dashboard"
Write-Host "  $VenvPython -m clue score"
Write-Host "  $VenvPython -m clue doctor"
Write-Host ""
