@echo off
chcp 65001 >nul 2>&1
rem ===========================================================================
rem  SETUP.bat - ติดตั้งครั้งแรกบนเครื่องใหม่ (สร้าง .venv + ติดตั้งไลบรารี)
rem ===========================================================================
setlocal EnableDelayedExpansion
title MADE - Setup
cd /d "%~dp0"

echo ===========================================================
echo   MADE - ติดตั้งครั้งแรก
echo ===========================================================

set "PY="
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo ไม่พบ Python - ติดตั้ง Python 3.12 จาก https://www.python.org/downloads/
    echo ตอนติดตั้งให้ติ๊ก "Add python.exe to PATH" และ "tcl/tk and IDLE"
    goto :die
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] สร้าง .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :die
) else (
    echo [1/3] มี .venv อยู่แล้ว
)

echo [2/3] ติดตั้งไลบรารีจาก requirements.txt ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ติดตั้งไม่สำเร็จ ดูข้อความ error ข้างบน
    goto :die
)

echo [3/3] ตรวจไฟล์ config ...
if not exist "webull_config.json" (
    copy /y "webull_config.example.json" "webull_config.json" >nul
    echo       สร้าง webull_config.json จากแม่แบบแล้ว
    echo       ** เปิดไฟล์นี้แล้วใส่ app_key / app_secret ของ Webull **
    echo       ^(ถ้าไม่ใช้ Webull ข้ามได้ แท็บที่เกี่ยวข้องจะว่าง^)
) else (
    echo       พบ webull_config.json แล้ว
)

echo.
echo ติดตั้งเสร็จแล้ว - เปิด MT5 ค้างไว้ แล้วดับเบิลคลิก MADE.bat
echo.
pause
endlocal
exit /b 0

:die
echo.
pause
endlocal
exit /b 1
