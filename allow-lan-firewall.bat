@echo off
setlocal EnableExtensions
title Manz Music Player - Firewall

rem Creates the inbound firewall rule that lets phones / other PCs on your
rem Wi-Fi reach the app. Run with /quiet to skip the pause (used by the launcher).

set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"

fltmc >nul 2>&1
if not errorlevel 1 goto elevated
if defined QUIET goto elevate_quiet

echo Requesting administrator permission...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:elevate_quiet
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Start-Process -FilePath '%~f0' -ArgumentList '/quiet' -Verb RunAs -Wait -ErrorAction Stop; exit 0 } catch { exit 1 }"
exit /b %ERRORLEVEL%

:elevated
set "VPY=%~dp0.venv\Scripts\python.exe"
if exist "%VPY%" goto add_rule

echo Start the app once with launch-windows.bat first.
echo The virtual environment is needed to create the firewall rule.
if not defined QUIET pause
exit /b 1

:add_rule
netsh advfirewall firewall delete rule name="Manz Music Player (LAN)" >nul 2>&1
netsh advfirewall firewall add rule name="Manz Music Player (LAN)" dir=in action=allow program="%VPY%" protocol=TCP localport=8642-8666 profile=private
if errorlevel 1 goto rule_failed
echo Firewall rule added for Private networks on ports 8642-8666.
echo.
if not defined QUIET pause
exit /b 0

:rule_failed
echo Could not add the firewall rule.
echo.
if not defined QUIET pause
exit /b 1
