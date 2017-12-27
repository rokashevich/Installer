@echo off


if "%2"== "" exit /b 1


set "BAT_FILE=%0"
set "REMOTE_HOST=%1"
set "INSTALL_PATH=%2"
set "TMP_FILE=%BAT_FILE:.bat=.part.txt%
set "RESULT_FILE=%BAT_FILE:.bat=.txt%

echo rh %REMOTE_HOST% > %TMP_FILE%
echo ip %INSTALL_PATH% >> %TMP_FILE%
echo success >> %TMP_FILE%
move /y %TMP_FILE% %RESULT_FILE%
