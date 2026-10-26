@echo off
setlocal
cd /d "%~dp0"
if not exist ".env" (
    echo RESULT: MISSING branch
) else (
    echo RESULT: EXISTS branch
)
echo ---with where py before---
where py >nul 2>nul && echo py-found
