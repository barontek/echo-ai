@echo off
setlocal EnableDelayedExpansion

REM Echo AI - Windows Launcher
REM Usage:
REM   run.bat           - Run React frontend + backend (development)
REM   run.bat dev      - Run React frontend + backend (for development)
REM   run.bat web     - Run FastAPI backend only
REM   run.bat chat    - Run CLI chat
REM   run.bat tui     - Run TUI
REM   run.bat install - Install dependencies only

set "MODE=%~1"
if "%MODE%"=="" set "MODE%"

REM ============================================
REM Setup Environment
REM ============================================

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Check if uv is installed
uv --version >nul 2>&1
if errorlevel 1 (
    echo Installing uv...
    pip install uv
)

REM Check if .venv exists
if not exist ".venv" (
    echo Creating virtual environment...
    uv venv .venv
)

REM Install dependencies if needed
uv pip install -e . >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    uv pip install -e .
)

REM Load environment variables from .env if present
if exist ".env" (
    echo Loading environment from .env...
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        set "%%a=%%b"
    )
)

REM ============================================
REM Run Mode
REM ============================================

if "%MODE%"=="" goto :dev
if "%MODE%"=="install" goto :install
if "%MODE%"=="dev" goto :dev
if "%MODE%"=="web" goto :web
if "%MODE%"=="chat" goto :chat
if "%MODE%"=="tui" goto :tui

echo Usage: run.bat [dev^|web^|chat^|tui^|install]
exit /b 1

:install
echo Dependencies installed.
goto :end

:dev
echo Starting Echo AI (Development Mode)...
echo.
echo ===================================
echo   Backend: http://localhost:8080
echo   Frontend: http://localhost:3000
echo ===================================
echo.

REM Start backend in background
start /b cmd /c ".venv\Scripts\python -m src.agentframework.web_api"
timeout /t 3 /nobreak >nul

REM Start frontend
cd frontend
call npm install --silent
call npm run dev
goto :end

:web
echo Starting FastAPI Backend on http://localhost:8080...
.venv\Scripts\python -m src.agentframework.web_api
goto :end

:chat
echo Starting CLI Chat...
.venv\Scripts\python -m src.agentframework.chat
goto :end

:tui
echo Starting TUI...
.venv\Scripts\python -m src.agentframework.tui
goto :end

:end
echo.
echo Done.
pause
