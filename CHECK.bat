@echo off
chcp 65001 >nul 2>&1
rem ===========================================================================
rem  CHECK.bat - component-by-component diagnostics
rem ===========================================================================
setlocal EnableDelayedExpansion
title MADE - ตรวจระบบ
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY for %%V in (3.12 3.11 3.10) do (
    if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY set "PY=python"

echo ===========================================================
echo   ตรวจระบบ MADE
echo ===========================================================
echo.
echo --- Python ---
%PY% -c "import sys,platform;print(' ',sys.version.split()[0],'|',platform.machine());print('  path:',sys.executable)"
echo.

echo --- ไลบรารี ---
for %%M in (pandas numpy tkinter MetaTrader5 webull rpyc) do (
    %PY% -c "import %%M" >nul 2>&1 && (echo   [มี]    %%M) || (echo   [ไม่มี] %%M)
)
echo.

echo --- ไฟล์ในโฟลเดอร์ ---
for %%F in (made_gui.py multi_asset_decision_engine.py webull_market.py webull_config.json news_calendar.py MADE_ZoneDrawer.mq5) do (
    if exist "%%F" (echo   [มี]    %%F) else (echo   [ไม่มี] %%F)
)
echo.

echo --- engine ---
%PY% -c "import importlib.util,sys;sp=importlib.util.spec_from_file_location('E','multi_asset_decision_engine.py');E=importlib.util.module_from_spec(sp);sys.modules['E']=E;sp.loader.exec_module(E);need=['make_source','analyze','CFG','ASSETS','compute_zones','export_zones_csv'];miss=[n for n in need if not hasattr(E,n)];print('  ครบทุกฟังก์ชัน' if not miss else '  ขาด: '+', '.join(miss));print('  chart_bars =',E.CFG.get('chart_bars','ไม่มี - แท็บกราฟจะว่าง'))" 2>&1
echo.

echo --- MT5 ---
%PY% -c "import MetaTrader5 as m;ok=m.initialize();print('  เชื่อมต่อ:',ok);a=m.account_info();print('  บัญชี:',a.login,a.company,a.balance,a.currency) if a else print('  อ่านบัญชีไม่ได้');[print('  ',s,m.symbol_info_tick(s).bid if m.symbol_select(s,True) and m.symbol_info_tick(s) else 'ไม่มีข้อมูล') for s in ['GOLDm#','USDX-DEC26','BRENTCash#','US30Cash#','US100Cash#','US500Cash#']];m.shutdown()" 2>&1
echo.

echo --- ข่าว + ปฏิทิน ---
if exist "news_calendar.py" (
    %PY% news_calendar.py 2>&1 | findstr /C:"━━" /C:"🔴" /C:"ดึง" /C:"ไม่"
) else (
    echo   ไม่มีไฟล์ news_calendar.py
)
echo.

echo --- Webull ---
if exist "webull_market.py" (
    %PY% webull_market.py 2>&1 | findstr /C:"ความเสี่ยง" /C:"ผิดพลาด" /C:"ยิงไป" /C:"สิทธิ์" /C:"จำกัด"
) else (
    echo   ไม่มีไฟล์ webull_market.py
)
echo.

echo ===========================================================
echo   ตรวจเสร็จ - คัดลอกผลทั้งหมดส่งให้เฟิร์นได้เลย
echo ===========================================================
pause
endlocal
