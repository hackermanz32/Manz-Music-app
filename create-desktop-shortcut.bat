@echo off
setlocal EnableExtensions
title Manz Music Player - Shortcut

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut((Join-Path $desktop 'Manz Music Player.lnk')); $s.TargetPath = '%~dp0launch-windows-lan.bat'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0icon.ico'; $s.Description = 'Manz Music Player (this PC + Wi-Fi devices)'; $s.Save()"

if errorlevel 1 (
  echo Could not create the desktop shortcut.
) else (
  echo Desktop shortcut created: Manz Music Player
  echo It starts LAN mode, so this PC and your phone both work with one click.
  echo The first launch asks for firewall permission once.
)
echo.
pause
