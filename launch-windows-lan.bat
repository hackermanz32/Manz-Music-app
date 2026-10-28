@echo off
setlocal EnableExtensions
title Manz Music Player - LAN

rem LAN mode: the app works on this PC and on any phone/PC on the same Wi-Fi.
rem The desktop shortcut points here, so one click starts everything.
set "MANZ_LAN=1"
call "%~dp0launch-windows.bat" --host 0.0.0.0 %*
exit /b %ERRORLEVEL%
