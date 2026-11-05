@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
%PY% webull_market.py --json webull_core_test.json > webull_core_test.txt 2>&1
type webull_core_test.txt
echo.
pause
