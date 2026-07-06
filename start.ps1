#Requires -Version 5.1
<#
.SYNOPSIS
    Imoveis system launcher - starts the complete stack with one command.
#>
param(
    [switch]$Stop,
    [switch]$Logs,
    [switch]$NoFrontend,
    [string]$OllamaModel = "llama3.2-vision"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
function Write-Step { param($msg) Write-Host "`n> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

function Wait-Until {
    param([ScriptBlock]$Condition, [string]$Label, [int]$MaxSeconds = 60)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $MaxSeconds) {
        if (& $Condition) { Write-OK "$Label is ready"; return }
        $sec = [int]$sw.Elapsed.TotalSeconds
        Write-Host "  ... waiting for $Label (${sec}s)" -ForegroundColor DarkGray
        Start-Sleep 3
    }
    Write-Fail "$Label did not become ready within ${MaxSeconds}s"
}

# -----------------------------------------------------------------------------
# Stop mode
# -----------------------------------------------------------------------------
if ($Stop) {
    Write-Step "Stopping all containers..."
    docker-compose -f "$ProjectRoot\docker-compose.yml" down
    Write-OK "All containers stopped."
    exit 0
}

# -----------------------------------------------------------------------------
# Log tail mode
# -----------------------------------------------------------------------------
if ($Logs) {
    docker-compose -f "$ProjectRoot\docker-compose.yml" logs -f
    exit 0
}

Write-Host @"
  ======================================================
  Real-Estate AI Ingestor - Stack Launcher
  ======================================================
"@ -ForegroundColor Magenta

# -----------------------------------------------------------------------------
# 1. Docker Desktop
# -----------------------------------------------------------------------------
Write-Step "Checking Docker Desktop..."
try {
    $null = docker info 2>&1
    Write-OK "Docker is running"
} catch {
    Write-Warn "Docker Desktop not running - attempting to start..."
    $dockerExe = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerExe) {
        Start-Process $dockerExe
        Wait-Until { try { $null = docker info 2>&1; $true } catch { $false } } "Docker Engine" 120
    } else {
        Write-Fail "Docker Desktop not found. Install it from https://docs.docker.com/desktop/install/windows-install/"
    }
}

# -----------------------------------------------------------------------------
# 2. Start infrastructure containers (postgres + redis)
# -----------------------------------------------------------------------------
Write-Step "Starting PostgreSQL + Redis..."
docker-compose -f "$ProjectRoot\docker-compose.yml" up -d postgres redis

Wait-Until {
    $r = docker-compose -f "$ProjectRoot\docker-compose.yml" ps postgres 2>&1 | Select-String "healthy"
    $r -ne $null
} "PostgreSQL" 60

Wait-Until {
    $r = docker-compose -f "$ProjectRoot\docker-compose.yml" ps redis 2>&1 | Select-String "healthy"
    $r -ne $null
} "Redis" 30

# -----------------------------------------------------------------------------
# 3. Ollama
# -----------------------------------------------------------------------------
Write-Step "Checking Ollama..."

function Test-OllamaAlive {
    try {
        $r = Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 3
        return $true
    } catch { return $false }
}

if (-not (Test-OllamaAlive)) {
    Write-Warn "Ollama not responding - starting 'ollama serve'..."
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Wait-Until { Test-OllamaAlive } "Ollama serve" 30
} else {
    Write-OK "Ollama is already running"
}

# Pull model if not present
Write-Step "Checking VLM model ($OllamaModel)..."
$tags = Invoke-RestMethod "http://localhost:11434/api/tags"
$modelPresent = $tags.models | Where-Object { $_.name -like "*$OllamaModel*" }
if (-not $modelPresent) {
    Write-Warn "Model not found locally - pulling $OllamaModel (this may take several minutes)..."
    & ollama pull $OllamaModel
    Write-OK "Model pulled"
} else {
    Write-OK "Model $OllamaModel is already available"
}

# -----------------------------------------------------------------------------
# 4. Build Images & DB Migrations
# -----------------------------------------------------------------------------
Write-Step "Building Docker images (uses cache if unchanged)..."
docker-compose -f "$ProjectRoot\docker-compose.yml" build api worker_ai worker_scraper

Write-Step "Running Alembic migrations inside container..."

try {
    $ErrorActionPreference = "Continue"
    docker-compose -f "$ProjectRoot\docker-compose.yml" run --rm api python -m alembic upgrade head
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    
    if ($exitCode -eq 0) {
        Write-OK "Migrations applied"
    } else {
        Write-Warn "Alembic failed with exit code $exitCode"
    }
} catch {
    Write-Warn "Alembic failed to execute: $_"
}

# -----------------------------------------------------------------------------
# 5. Start API + Workers
# -----------------------------------------------------------------------------
Write-Step "Starting API and Celery workers..."
docker-compose -f "$ProjectRoot\docker-compose.yml" up --build -d api worker_ai worker_scraper

Wait-Until {
    try {
        $r = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 3
        $r.status -eq "ok" -or $r.status -eq "degraded"
    } catch { $false }
} "FastAPI" 60

Write-OK "API is up at http://localhost:8000"

# -----------------------------------------------------------------------------
# 6. Frontend
# -----------------------------------------------------------------------------
if (-not $NoFrontend) {
    Write-Step "Starting React frontend..."
    $frontendPath = "$ProjectRoot\frontend"
    if (-not (Test-Path "$frontendPath\node_modules")) {
        Write-Warn "Installing frontend dependencies..."
        Push-Location $frontendPath
        npm install
        Pop-Location
    }
    Start-Process "cmd" -ArgumentList "/c", "cd /d `"$frontendPath`" && npm run dev" -WindowStyle Normal
    Start-Sleep 4
    Write-OK "Frontend started at http://localhost:5173"
    Start-Process "http://localhost:5173"
}

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
Write-Host @"

  [+] STACK IS RUNNING
      Frontend -> http://localhost:5173
      API docs -> http://localhost:8000/docs
      Ollama   -> http://localhost:11434

  To stop:         .\start.ps1 -Stop
  To follow logs:  .\start.ps1 -Logs
"@ -ForegroundColor Magenta
