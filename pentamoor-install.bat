@echo off
rem pentamoor-install.bat ["path\to\MTG v1.0.iso"] [options]: install the game from your own disc image and build its game modules, ready for pentamoor.bat.
rem Runs the same pentamoor-install Python program as the other systems: the Python that comes in the release (python\python.exe), else py -3, else python on the PATH.
rem With no file name it asks for one: type or paste the path, or drag the .iso file onto this window.
setlocal
cd /d "%~dp0" || exit /b 1
set "PY="
if exist "python\python.exe" set "PY=python\python.exe"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo pentamoor-install: Python 3 was not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  exit /b 1
)
%PY% -c "import sys; sys.path.insert(0, 'tools/install'); import install; install.main(default_build=True)" %*
exit /b %ERRORLEVEL%
