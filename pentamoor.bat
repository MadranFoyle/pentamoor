@echo off
rem pentamoor.bat [deck|duel|sota] [more arguments]: run the game (or its standalone deck builder or duel program). The same as ./pentamoor. `sota` is Spells of the Ancients 2.15 (experimental):
rem the folder that holds its shandalar.exe is %PENTAMOOR_SOTA% (default sources\installed_sota\Program), built by tools\install\install_sota.py (docs/notes/sota-comparison.md, "Milestone 1").
rem Double click it: the first time it offers to install the game (it asks for your disc image, an .iso file; type or paste the path or drag the file onto the window), then it runs it.
rem Drop an .iso file on it, or pentamoor.bat "D:\MTG v1.0.iso", to install from that disc image first.
rem It starts the runtime (pentamoor-run.exe, no game code in it) with the game module (game_magic.dll, game_deck.dll or game_duel.dll, the C made from your own files) for
rem that program. Saves go to port_overlay (a folder beside this file). Set PENTAMOOR_GAME to another game folder (the one that holds MAGIC.EXE), PORT_RES=640x480 for the
rem original size (the default is 1024x768), PENTAMOOR_RUN to another runtime, PENTAMOOR_MODULE to another game module.
rem Where it looks: a pentamoor-run.exe and game_*.dll beside this file (a release), else src\port\build\ (a build from source).
setlocal
cd /d "%~dp0" || exit /b 1

rem started by a double click (cmd was given this file to run) rather than from a command prompt: keep the window open when something goes wrong
set "PAUSE_AT_END="
echo %cmdcmdline% | find /i "%~0" >nul && set "PAUSE_AT_END=1"

set "GAME=%PENTAMOOR_GAME%"
if "%GAME%"=="" set "GAME=sources\installed\Magic\Program"

rem an .iso as the first argument (a file dropped on this one): install from it first
if /i "%~x1"==".iso" if exist "%~1" (
  call pentamoor-install.bat "%~1"
  if errorlevel 1 goto failed
  shift
)

set "PROG=magic"
set "EXE=MAGIC.EXE"
if /i "%~1"=="sota" (
  set "PROG=shandalar"
  set "EXE=shandalar.exe"
  set "GAME=%PENTAMOOR_SOTA%"
  if "%PENTAMOOR_SOTA%"=="" set "GAME=sources\installed_sota\Program"
  shift
) else if /i "%~1"=="deck" (
  set "PROG=deck"
  set "EXE=DECK.EXE"
  shift
) else if /i "%~1"=="duel" (
  set "PROG=duel"
  set "EXE=DUEL.EXE"
  shift
)

set "BUILD=src\port\build"
if exist "pentamoor-run.exe" set "BUILD=."
set "RUN=%PENTAMOOR_RUN%"
if "%RUN%"=="" set "RUN=%BUILD%\pentamoor-run.exe"
set "MODULE=%PENTAMOOR_MODULE%"
if "%MODULE%"=="" set "MODULE=%BUILD%\game_%PROG%.dll"

rem Spells of the Ancients: no installer offer (it is built from a folder you assembled: python tools\install\install_sota.py)
if "%PROG%"=="shandalar" goto checks

rem not installed (or not built) yet: in a release, offer to run the installer now
set "WHY="
if not exist "%GAME%\%EXE%" set "WHY=the game is not installed yet (%GAME%\%EXE% is missing)"
if not defined WHY if not exist "%MODULE%" set "WHY=the game module is not built yet (%MODULE% is missing)"
if defined WHY if exist "pentamoor-install.bat" if "%PENTAMOOR_GAME%%PENTAMOOR_MODULE%%PENTAMOOR_RUN%"=="" goto offer
goto checks

:offer
echo pentamoor: %WHY%.
echo Pentamoor builds the game from your own copy of it: a disc image (an .iso file) of the retail Magic: The Gathering CD, version 1.0.
echo That takes a few minutes (2 to 15, depending on the computer), once, and up to 1 GB of free disk space while it works.
set "ANSWER=Y"
set /p "ANSWER=Install it now? [Y/n] "
if /i "%ANSWER:~0,1%"=="n" goto end
call pentamoor-install.bat
if errorlevel 1 goto failed

:checks
if not exist "%GAME%\%EXE%" (
  echo pentamoor: the game is not installed ^(%GAME%\%EXE% is missing^).
  echo   pentamoor-install.bat "path\to\MTG v1.0.iso"     ^(from a source checkout: python tools\install\install.py "path\to\MTG v1.0.iso" --build^)
  goto failed
)
if not exist "%RUN%" (
  echo pentamoor: the runtime is not built yet ^(%RUN% is missing^).
  echo   python tools\install\install.py "path\to\MTG v1.0.iso" --build     ^(or: make -C src/port runtime, in an MSYS2 shell^)
  goto failed
)
if not exist "%MODULE%" (
  echo pentamoor: the game module is not built yet ^(%MODULE% is missing^).
  echo   pentamoor-install.bat     ^(from a source checkout: python tools\install\install.py "path\to\MTG v1.0.iso" --build^)
  goto failed
)

rem what is left of the command line after deck or duel
set "REST="
:next
if "%~1"=="" goto run
set REST=%REST% %1
shift
goto next

:run
"%RUN%" -m "%MODULE%" "%GAME%\%EXE%" %REST%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" if defined PAUSE_AT_END pause
exit /b %RC%

:failed
if defined PAUSE_AT_END pause
exit /b 1

:end
exit /b 0
