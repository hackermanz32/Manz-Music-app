@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title Manz Music Player

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "VPY=%VENV%\Scripts\python.exe"

cd /d "%ROOT%"

if not exist "%VPY%" goto find_or_install

"%VPY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 goto check_deps
echo Existing virtual environment is not compatible. Rebuilding...
rmdir /s /q "%VENV%"

:find_or_install
set "PYEXE="
call :find_python
if not defined PYEXE call :install_python
call :find_python
if not defined PYEXE goto no_python
echo Creating virtual environment...
"%PYEXE%" -m venv "%VENV%"
if errorlevel 1 goto venv_failed

:check_deps
"%VPY%" -c "import mutagen, imageio_ffmpeg, yt_dlp, PIL" >nul 2>nul
if not errorlevel 1 goto run_app

echo Installing required packages (first run only)...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check
"%VPY%" -m pip install -r "%ROOT%requirements.txt" --disable-pip-version-check
if errorlevel 1 goto deps_failed
"%VPY%" -c "import mutagen, imageio_ffmpeg, yt_dlp, PIL" >nul 2>nul
if errorlevel 1 goto deps_failed

:run_app
if defined MANZ_LAN call :ensure_firewall
if defined MANZ_LAN (title Manz Music Player - LAN) else (title Manz Music Player)
echo.
echo Starting Manz Music Player...
echo Keep this window open. Close it to stop the server.
echo.
"%VPY%" server.py %*
set "APP_EXIT=%ERRORLEVEL%"
echo.
if not "%APP_EXIT%"=="0" echo The app stopped with error code %APP_EXIT%.
pause
exit /b %APP_EXIT%

:find_python
set "PYEXE="
for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable) if sys.version_info>=(3,10) else sys.exit(1)" 2^>nul') do if exist "%%~I" set "PYEXE=%%I"
if defined PYEXE exit /b 0
for /f "delims=" %%I in ('python -c "import sys;print(sys.executable) if sys.version_info>=(3,10) else sys.exit(1)" 2^>nul') do if exist "%%~I" set "PYEXE=%%I"
if defined PYEXE exit /b 0
for %%I in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "%ProgramFiles%\Python310\python.exe"
) do if exist "%%~I" set "PYEXE=%%~I"
if defined PYEXE exit /b 0
exit /b 1

:install_python
where winget >nul 2>nul
if errorlevel 1 exit /b 1
echo.
echo Python 3 was not found. Installing Python 3.12 with winget...
echo If Windows asks for permission, allow it.
winget install --id Python.Python.3.12 -e --source winget --accept-source-agreements --accept-package-agreements --silent
set "PATH=%LOCALAPPDATA%\Programs\Python\Launcher;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%PATH%"
exit /b 0

:no_python
echo.
echo Python 3.10 or newer is required.
echo Install it from https://www.python.org/downloads/windows/
echo Important: tick "Add python.exe to PATH" during installation.
echo Then run launch-windows.bat again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo Could not create the virtual environment in:
echo   %VENV%
echo Make sure the folder is writable and you copied all files.
echo.
pause
exit /b 1

:deps_failed
echo.
echo Dependency installation failed.
echo Check your internet connection and run launch-windows.bat again.
echo If it keeps failing, delete the .venv folder and retry.
echo.
pause
exit /b 1

:ensure_firewall
if not exist "%VPY%" exit /b 0
netsh advfirewall firewall show rule name="Manz Music Player (LAN)" >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo Allowing Manz Music Player through Windows Firewall (one time only)...
echo If Windows asks for permission, choose Yes.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath '%ROOT%allow-lan-firewall.bat' -ArgumentList '/quiet' -Verb RunAs -Wait -ErrorAction Stop; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Could not add the firewall rule automatically.
  echo If your phone cannot connect, right-click allow-lan-firewall.bat and pick "Run as administrator".
) else (
  echo Firewall rule ready for your local network.
)
echo.
exit /b 0

