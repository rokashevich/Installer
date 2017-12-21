@echo off


rem Скрипт для проверки установки, путь к которой передаётся первым аргументом.
rem verify.bat D:\st\simulator


if "%1"== "" exit /b 1


rem ПРИНЦИП РАБОТЫ
rem
rem Installer копирует данный скрипт на удалённую машину в уникальный файл
rem например C:\Windows\Temp\20171129194455.bat и запускает на исполнение 
rem чрез wmic c аргументом пути установки дистрибутива (INSTALL_PATH):
rem 	C:\Windows\Temp\20171129194455.bat C:\ST_XXX\Main\simulator
rem
rem Данный скрипт переходит в INSTALL_PATH, находит в нём base.txt и проверяет 
rem его, записывая результат проверки в C:\Windows\Temp\20171129194455.part.txt 
rem (TMP_FILE). По окончании проверки переименовывает TMP_FILE в 
rem 20171129194455.txt (RESULT_FILE)
rem 
rem Installer же всё это время ожидает появления RESULT_FILE, и по появлении его
rem скачивает и выводит результат в интерфейс.


set "BAT_FILE=%0"
set "INSTALL_PATH=%1"
set "TMP_FILE=%BAT_FILE:.bat=.part.txt%
set "RESULT_FILE=%BAT_FILE:.bat=.txt%
set "BASE_TXT_FILE=%INSTALL_PATH%\base.txt"


cd /d %INSTALL_PATH%


if not exist "%BASE_TXT_FILE%" (
echo error file not found %BASE_TXT_FILE% >> %TMP_FILE%
goto FINISH
)


for /f "tokens=1,2,* delims= " %%a in (%BASE_TXT_FILE%) do call :PARSE_STRING %%a %%b "%%c"


:FINISH
if not exist %TMP_FILE% (
echo success > %RESULT_FILE%
) else move %TMP_FILE% %RESULT_FILE%
exit /b 0


:PARSE_STRING
if not "%1"=="md5" exit /b
set MD5_FROM_BASE_TXT=%2
set FILE_RELATIVE_PATH=%3
if not exist %FILE_RELATIVE_PATH% (
	echo error file not found %FILE_RELATIVE_PATH% >> %TMP_FILE%
	exit /b
)
setlocal enabledelayedexpansion
for /f "delims=" %%_ in ('certutil -hashfile %FILE_RELATIVE_PATH% MD5 ^| find /v ":"') do (
set "MD5=%%_"
set "MD5=!MD5: =!"
if not "!MD5!"=="%MD5_FROM_BASE_TXT%" echo error md5 %FILE_RELATIVE_PATH% >> %TMP_FILE%
)
