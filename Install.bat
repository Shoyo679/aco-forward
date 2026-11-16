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
rem     If it's missing, the official installer is downloaded from python.org, checked (exact fingerprint + signed by
rem     the Python Software Foundation) and installed quietly for this Windows account only (no admin needed).
set "PYVER=3.13.9"
set "PYURL=https://www.python.org/ftp/python/3.13.9/python-3.13.9-amd64.exe"
set "PYSHA=200DDFF856BBFF949D2CC1BE42E8807C07538ABD6B6966D5113A094CF628C5C5"
set "PYHOME=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "PY="
py -3.13 -c "" >nul 2>nul && set "PY=py -3.13"
if not defined PY if exist "%PYHOME%" set "PY="%PYHOME%""
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY goto getpython
goto havepython

:getpython
echo  Python isn't installed yet. Downloading Python %PYVER% from python.org ^(about 28 MB^)...
set "PYEXE=%TEMP%\aco-forward-python-%PYVER%.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest '%PYURL%' -OutFile '%PYEXE%' -UseBasicParsing } catch { exit 1 }; if ((Get-FileHash '%PYEXE%' -Algorithm SHA256).Hash -ne '%PYSHA%') { Remove-Item '%PYEXE%'; exit 2 }; $s = Get-AuthenticodeSignature '%PYEXE%'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*Python Software Foundation*') { Remove-Item '%PYEXE%'; exit 3 }; exit 0"
if errorlevel 3 goto pybad
if errorlevel 2 goto pybad
if errorlevel 1 goto pynet
echo  Installing Python %PYVER% for your Windows account ^(1-2 minutes, no windows to click^)...
start "" /wait "%PYEXE%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 Include_doc=0 Shortcuts=0
del "%PYEXE%" >nul 2>nul
if not exist "%PYHOME%" goto pyfail
set "PY="%PYHOME%""
echo  Python %PYVER% installed.

:havepython

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

:pynet
echo.
echo  Couldn't download Python. Check your internet connection and run Install.bat again.
echo.
pause
exit /b 1

:pybad
echo.
echo  The downloaded Python installer didn't pass the safety check, so it was deleted and nothing was installed.
echo  Run Install.bat again. If it happens again, install Python 3.13 yourself from https://www.python.org/downloads/
echo  ^(tick "Add python.exe to PATH"^), then run Install.bat.
echo.
pause
exit /b 1

:pyfail
echo.
echo  Python didn't finish installing. Install Python 3.13 yourself from https://www.python.org/downloads/
echo  ^(tick "Add python.exe to PATH"^), then run Install.bat again.
echo.
start "" "https://www.python.org/downloads/"
pause
exit /b 1
