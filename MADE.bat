@echo off
chcp 65001 >nul 2>&1
rem ===========================================================================
rem  MADE.bat - launcher for Multi-Asset Decision Engine
rem  Put this next to made_gui.py and double-click it.
rem ===========================================================================
setlocal EnableDelayedExpansion
title MADE - Multi-Asset Decision Engine
cd /d "%~dp0"

echo ===========================================================
echo   MADE - Multi-Asset Decision Engine
echo   โฟลเดอร์: %CD%
echo ===========================================================
echo.

rem --- 1) หา Python ที่ใช้ได้ -------------------------------------------------
rem     MetaTrader5 รองรับ 3.8-3.12 เท่านั้น จึงไล่หาเวอร์ชันที่ใช้ได้ก่อน
set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [1/4] ใช้ Python จาก .venv
    goto :found
)
for %%V in (3.12 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && (
            set "PY=py -%%V"
            echo [1/4] ใช้ Python %%V
        )
    )
)
if not defined PY (
    python -c "import sys" >nul 2>&1 && (
        set "PY=python"
        echo [1/4] ใช้ python ที่อยู่ใน PATH
    )
)

:found
if not defined PY (
    echo [1/4] ไม่พบ Python
    echo.
    echo     ติดตั้ง Python 3.12 จาก https://www.python.org/downloads/
    echo     ตอนติดตั้งให้ติ๊ก "Add python.exe to PATH"
    goto :die
)

rem --- 2) เตือนถ้าเวอร์ชันใหม่เกินไป ------------------------------------------
for /f "delims=" %%A in ('%PY% -c "import sys;print(sys.version_info[1])" 2^>nul') do set "MINOR=%%A"
if defined MINOR (
    if !MINOR! GEQ 13 (
        echo       เตือน: Python 3.!MINOR! ใหม่เกินไปสำหรับ MetaTrader5 ^(รองรับถึง 3.12^)
        echo              โหมด MT5 native จะใช้ไม่ได้ ให้ใช้โหมดไฟล์ JSON แทน
    )
)

rem --- 3) ตรวจไฟล์ที่จำเป็น ---------------------------------------------------
if not exist "made_gui.py" (
    echo [2/4] ไม่พบ made_gui.py ในโฟลเดอร์นี้
    goto :die
)
if not exist "multi_asset_decision_engine.py" (
    echo [2/4] ไม่พบ multi_asset_decision_engine.py
    goto :die
)
echo [2/4] ไฟล์หลักครบ

set "OPT="
if not exist "webull_market.py"  set "OPT=!OPT! webull_market.py"
if not exist "webull_config.json" set "OPT=!OPT! webull_config.json"
if not exist "news_calendar.py"  set "OPT=!OPT! news_calendar.py"
if defined OPT echo       ไม่มีไฟล์เสริม:!OPT! ^(แท็บที่เกี่ยวข้องจะว่าง^)

rem --- 4) ตรวจไลบรารี ---------------------------------------------------------
%PY% -c "import pandas, numpy" >nul 2>&1
if errorlevel 1 (
    echo [3/4] ยังไม่มี pandas/numpy - กำลังติดตั้ง...
    %PY% -m pip install --quiet --upgrade pip
    %PY% -m pip install --quiet pandas numpy
    if errorlevel 1 (
        echo       ติดตั้งไม่สำเร็จ ลองสั่งเองด้วย: %PY% -m pip install pandas numpy
        goto :die
    )
    echo       ติดตั้งเสร็จแล้ว
) else (
    echo [3/4] pandas / numpy พร้อม
)

%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [3/4] ไม่พบ tkinter - ต้องติดตั้ง Python ใหม่โดยติ๊ก "tcl/tk and IDLE"
    goto :die
)

rem --- 5) เตือนเรื่อง log ของ Webull ที่โตเร็ว --------------------------------
if exist "webull_data_sdk.log" (
    for %%F in (webull_data_sdk.log) do set /a "LOGMB=%%~zF/1048576"
    if !LOGMB! GTR 20 (
        echo       log ของ Webull โต !LOGMB! MB - กำลังล้าง
        type nul > webull_data_sdk.log
    )
)

rem --- 6) เปิดโปรแกรม ---------------------------------------------------------
echo [4/4] เปิด dashboard...
echo.
echo       อย่าลืมเปิด MT5 ค้างไว้ และเปิด symbol ครบ 6 ตัวใน Market Watch
echo.
%PY% made_gui.py
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo ปิดโปรแกรมเรียบร้อย
    timeout /t 3 >nul
    goto :eof
)

echo ===========================================================
echo   โปรแกรมจบด้วย error code %RC%
echo   คัดลอกข้อความข้างบนส่งให้เฟิร์นดูได้เลย
echo ===========================================================

:die
echo.
pause
endlocal
