@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title RS Leech Lite v3.1

if exist ".venv\Scripts\python.exe" goto run

echo [setup] No .venv found - locating Python 3.13 ...
set "PY313="
py -3.13 -c "import sys" >nul 2>nul && set "PY313=py -3.13"
if not defined PY313 (
    python3.13 -c "import sys" >nul 2>nul && set "PY313=python3.13"
)
if not defined PY313 (
    if exist "..\.pyruntime\python\python.exe" set "PY313=..\.pyruntime\python\python.exe"
)
if not defined PY313 goto nopy

echo [setup] Creating the environment with %PY313% ...
%PY313% -m venv .venv
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

:run
".venv\Scripts\python.exe" main.py
goto end

:nopy
echo [error] Python 3.13 was not found on this PC.
echo         wzgram needs Python 3.10-3.13 (3.14 is not supported yet).
echo         Install Python 3.13 from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH", then run start.bat again.
pause
exit /b 1

:fail
echo [error] Setup failed. Check your internet connection and try again.
pause
exit /b 1

:end
if errorlevel 1 pause
