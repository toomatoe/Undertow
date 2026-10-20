<#
.SYNOPSIS
  Start Afterfile locally on Windows (Docker Desktop required, nothing else).

.DESCRIPTION
  - Creates .env from .env.example on the first run (every setting in it is optional).
  - Starts Postgres + API, and by default the web UI container too, all bound to 127.0.0.1.
  - Prints the local URLs.

  Usage (from the repo root or anywhere):
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1           # db + api + web UI
    powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -NoWeb    # db + api; run the UI with npm instead

.PARAMETER NoWeb
  Skip the web container (use this if you run `npm --prefix frontend run dev` on port 3000).
#>
[CmdletBinding()]
param(
    [switch]$NoWeb
)

# 'Continue', not 'Stop': Windows PowerShell 5.1 turns docker's stderr progress output into error records,
# which 'Stop' would make fatal. Failures are detected through $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. .env (optional settings). Copy the template on first run; never overwrite an existing file.
$envFile = Join-Path $root '.env'
$envExample = Join-Path $root '.env.example'
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item -LiteralPath $envExample -Destination $envFile -ErrorAction Stop
        Write-Host 'Created .env from .env.example (all settings optional; edit it any time).' -ForegroundColor Cyan
    } else {
        Write-Host '.env.example not found; continuing with built-in defaults.' -ForegroundColor Yellow
    }
}

# 2. Docker must be installed and running.
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $docker) {
    Write-Host ''
    Write-Host 'Docker was not found on PATH.' -ForegroundColor Red
    Write-Host 'Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then run this script again.'
    exit 1
}

& docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'Docker is installed but not running. Start Docker Desktop, wait until it says "running", then try again.' -ForegroundColor Red
    exit 1
}

# 3. Start the stack.
if ($NoWeb) {
    $composeArgs = @('compose', 'up', '-d', '--build')
} else {
    $composeArgs = @('compose', '--profile', 'web', 'up', '-d', '--build')
}
Write-Host ('Running: docker ' + ($composeArgs -join ' ')) -ForegroundColor Cyan
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'docker compose failed (see the output above). If port 3000 is already in use by `npm run dev`, rerun with -NoWeb.' -ForegroundColor Red
    exit $LASTEXITCODE
}

# 4. Where to go next.
Write-Host ''
Write-Host 'Afterfile is starting (the first ingest can take a minute).' -ForegroundColor Green
if ($NoWeb) {
    Write-Host '  UI:   run  npm --prefix frontend install  (first time), then  npm --prefix frontend run dev'
    Write-Host '        and open http://localhost:3000'
} else {
    Write-Host '  UI:   http://localhost:3000'
}
Write-Host '  API:  http://localhost:8000/api/health'
Write-Host ('  Docs: ' + (Join-Path $root 'README.md') + ' and ' + (Join-Path $root 'docs'))
Write-Host ''
Write-Host 'Stop with:  docker compose --profile web down   (data is kept in Docker volumes)'
