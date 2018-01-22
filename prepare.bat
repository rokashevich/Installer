@echo off
cd %~dp0
set "BASE=%1"
set "HANDLE_EXE=handle%~n0.exe"
for /f "tokens=3,6,8 delims=: " %%i in ('%HANDLE_EXE% -accepteula -nobanner "%BASE%"') do %HANDLE_EXE% -c %%j -y -p %%i
if exist %BASE% ( del /f/s/q %BASE% > nul & rd /s/q %BASE% )
