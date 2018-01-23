@echo off
set "BASE=%1"
rem C:\Windows\Temp\handle64.exe -accepteula -nobanner "%BASE%"
rem echo -----
setlocal enabledelayedexpansion
for /f "tokens=3 delims= " %%a in ('C:\Windows\Temp\handle64.exe -accepteula -nobanner "%BASE%"') do (
echo taskkill /t /f /pid %1
)
if exist %BASE% ( del /f/s/q %BASE% > nul & rd /s/q %BASE% )
