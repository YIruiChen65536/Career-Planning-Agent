@echo off
setlocal
title Career Planning Agent Launcher
cd /d "%~dp0"

echo ============================================
echo   Career Planning Agent - One-click Start
echo ============================================
echo.

REM ---------- 1. Find Python ----------
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
    echo [ERROR] Python not found. Install Python 3.11+ from python.org
    echo         IMPORTANT: check "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

REM ---------- 2. Create venv if missing ----------
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] First run: creating venv...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed
        pause
        exit /b 1
    )
) else (
    echo [1/3] venv exists, skip
)

set "VPY=.venv\Scripts\python.exe"

REM ---------- 3. Install deps if missing ----------
%VPY% -c "import fastapi, pydantic_ai, pandas" >nul 2>nul
if errorlevel 1 (
    echo [2/3] Installing dependencies...
    %VPY% -m pip install -q -r requirements.lock.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed, check network
        pause
        exit /b 1
    )
) else (
    echo [2/3] deps ready, skip
)

REM ---------- 4. Check .env (API key required) ----------
if not exist ".env" (
    copy /y .env.example .env >nul
    echo [3/3] .env created from template.
    echo.
    echo  =========================================================
    echo   NO API KEY FOUND - the app cannot run without one.
    echo   1. Open .env in this folder with Notepad
    echo   2. Get a key yourself:
    echo      DeepSeek: platform.deepseek.com - key starts with sk-
    echo      Zhipu:    open.bigmodel.cn - has free tier
    echo   3. Paste it into DEEPSEEK_API_KEY= or ZAI_API_KEY=
    echo   4. Save, then run this .bat again.
    echo   NOTE: No API key is bundled with this repo.
    echo  =========================================================
    echo.
    start notepad .env
    pause
    exit /b 0
)

REM ---------- 5. Start server ----------
echo.
echo [START] http://127.0.0.1:8000/  - close this window to stop
echo.
start "" http://127.0.0.1:8000/
.venv\Scripts\python.exe -m uvicorn server:app --port 8000
pause
