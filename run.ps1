#!/usr/bin/env pwsh

# Echo AI - Windows PowerShell Launcher
# Usage:
#   run.ps1           - Run React frontend + backend (development)
#   run.ps1 dev      - Run React frontend + backend (for development)
#   run.ps1 web     - Run FastAPI backend only
#   run.ps1 chat    - Run CLI chat
#   run.ps1 tui     - Run TUI
#   run.ps1 install - Install dependencies only

param(
    [string]$Mode = ""
)

# ============================================
# Setup Environment
# ============================================

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found: $pythonVersion"
} catch {
    Write-Host "ERROR: Python not found. Please install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}

# Check uv
try {
    $uvVersion = uv --version 2>&1
} catch {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    pip install uv
}

# Create venv if needed
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    uv venv .venv
}

# Install dependencies if needed
Write-Host "Installing dependencies..." -ForegroundColor Yellow
uv pip install -e . --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    uv pip install -e .
}

# Load .env if present
if (Test-Path ".env") {
    Write-Host "Loading environment from .env..." -ForegroundColor Cyan
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
}

# ============================================
# Run Mode
# ============================================

if ($Mode -eq "") { $Mode = "dev" }

switch ($Mode) {
    "install" {
        Write-Host "Dependencies installed." -ForegroundColor Green
    }

    "dev" {
        Write-Host ""
        Write-Host "==================================" -ForegroundColor Cyan
        Write-Host "  Echo AI (Development Mode)" -ForegroundColor Cyan
        Write-Host "  Backend: http://localhost:8080" -ForegroundColor Cyan
        Write-Host "  Frontend: http://localhost:3000" -ForegroundColor Cyan
        Write-Host "==================================" -ForegroundColor Cyan
        Write-Host ""

        # Kill any old backend process on port 8080
        $oldProc = Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
        if ($oldProc) {
            Write-Host "Killing old backend process (PID: $oldProc)..." -ForegroundColor Yellow
            Stop-Process -Id $oldProc -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }

        # Start backend as visible process (output goes to console)
        Write-Host "Starting backend..." -ForegroundColor Yellow
        $backend = Start-Process -NoNewWindow -PassThru -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m", "src.agentframework.web_api"

        try {
            Start-Sleep -Seconds 3

            # Start frontend (foreground, blocking)
            Write-Host "Starting frontend..." -ForegroundColor Yellow
            Push-Location "frontend"
            if (-not (Test-Path "node_modules")) {
                npm install --silent
            }
            npm run dev
        } finally {
            Pop-Location
            # Cleanup backend when frontend exits
            Write-Host "Stopping backend..." -ForegroundColor Yellow
            if ($backend -and !$backend.HasExited) {
                $backend.Kill($true)
            }
        }
    }

    "web" {
        Write-Host "Starting FastAPI Backend on http://localhost:8080..." -ForegroundColor Cyan
        & ".venv\Scripts\python.exe" -m src.agentframework.web_api
    }

    "chat" {
        Write-Host "Starting CLI Chat..." -ForegroundColor Cyan
        & ".venv\Scripts\python.exe" -m src.agentframework.chat
    }

    "tui" {
        Write-Host "Starting TUI..." -ForegroundColor Cyan
        & ".venv\Scripts\python.exe" -m src.agentframework.tui
    }

    default {
        Write-Host "Usage: run.ps1 [dev|web|chat|tui|install]" -ForegroundColor Yellow
        exit 1
    }
}
