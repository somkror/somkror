@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
%PY% webull_extra_test.py
echo.
pause
