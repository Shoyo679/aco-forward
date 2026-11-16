@echo off
rem ACO Forward: install, or update after unzipping a new version. Safe to run again any time.
rem Your data (checkouts, fees, settings, token) lives in %LOCALAPPDATA%\ACO Forward and is never touched here.
setlocal
cd /d "%~dp0"
title ACO Forward setup
echo.
echo  ACO Forward setup
echo  =================
echo.

rem --- ACO Forward must be closed (its files are in use while it runs) ---
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',8787);$c.Close();exit 1}catch{exit 0}" >nul 2>nul
if errorlevel 1 (
  echo  ACO Forward is running. Right-click its tray icon ^(the monkey^), choose "Quit ACO Forward",
  echo  then run Install.bat again.
  echo.
  pause
  exit /b 1
)

rem --- find Python 3.13 (or 3.11+) ---
set "PY="
py -3.13 -c "" >nul 2>nul && set "PY=py -3.13"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo  Python 3.13 isn't installed.
  echo  1. Download it from https://www.python.org/downloads/  ^(Windows installer, 64-bit^)
  echo  2. In the installer, tick "Add python.exe to PATH", then Install Now.
  echo  3. Run Install.bat again.
  echo.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

rem --- the app's own Python environment (.venv, inside this folder) ---
if not exist ".venv\Scripts\python.exe" (
  echo  [1/3] Creating the app's Python environment...
  %PY% -m venv .venv || goto fail
) else (
  echo  [1/3] Python environment found.
)

echo  [2/3] Installing or updating packages ^(first time takes a minute^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto fail
".venv\Scripts\python.exe" -c "import discord, webview, pystray, PIL" || goto fail

echo  [3/3] Making the Desktop and Start menu shortcuts...
".venv\Scripts\python.exe" aco_forward.py --install-shortcuts >nul || goto fail

for /f "tokens=2 delims==" %%v in ('findstr /b "VERSION" version.py') do set "VER=%%v"
set "VER=%VER:"=%"
echo.
echo  Done. ACO Forward%VER% is ready.
echo  Open it from the Desktop shortcut "ACO Forward". GUIDE.md in this folder explains everything.
echo.
choice /c YN /m " Open ACO Forward now"
if errorlevel 2 exit /b 0
start "" ".venv\Scripts\pythonw.exe" aco_forward.py
exit /b 0

:fail
echo.
echo  Something went wrong (see the lines above). Check your internet connection and run Install.bat again.
echo  If it keeps failing, send a screenshot of this window to the person who gave you ACO Forward.
echo.
pause
exit /b 1
