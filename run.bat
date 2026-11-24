@echo off
setlocal EnableExtensions
title DXC Sage
cd /d "%~dp0"

set "API_PORT=29700"
set "WEB_PORT=29701"

rem Non-interactive use: run.bat start|stop|restart [api|web|all]
if not "%~1"=="" goto cli

:menu
cls
call :isup %API_PORT% && (set "S_API=running") || (set "S_API=stopped")
call :isup %WEB_PORT% && (set "S_WEB=running") || (set "S_WEB=stopped")
echo ==========================================
echo   DXC Sage  (runs directly on Windows)
echo ==========================================
echo   API  http://localhost:%API_PORT%   %S_API%
echo   Web  http://localhost:%WEB_PORT%   %S_WEB%
echo ------------------------------------------
echo   1  Start both       2  Stop both       3  Restart both
echo   4  Start API        5  Stop API        6  Restart API
echo   7  Start Web        8  Stop Web        9  Restart Web
echo   O  Open the app in the browser
echo   0  Exit
echo ------------------------------------------
set "c="
set /p "c=Choose: "
if "%c%"=="1" goto start_both
if "%c%"=="2" goto stop_both
if "%c%"=="3" goto restart_both
if "%c%"=="4" ( call :start_api & goto done )
if "%c%"=="5" ( call :stop_port %API_PORT% API & goto done )
if "%c%"=="6" ( call :stop_port %API_PORT% API & call :wait & call :start_api & goto done )
if "%c%"=="7" ( call :start_web & goto done )
if "%c%"=="8" ( call :stop_port %WEB_PORT% Web & goto done )
if "%c%"=="9" ( call :stop_port %WEB_PORT% Web & call :wait & call :start_web & goto done )
if /i "%c%"=="O" ( start "" "http://localhost:%WEB_PORT%" & goto menu )
if "%c%"=="0" exit /b 0
goto menu

:start_both
call :start_api
call :start_web
goto done

:stop_both
call :stop_port %API_PORT% API
call :stop_port %WEB_PORT% Web
goto done

:restart_both
call :stop_port %API_PORT% API
call :stop_port %WEB_PORT% Web
call :wait
call :start_api
call :start_web
goto done

:done
echo.
pause
goto menu

:cli
set "tgt=%~2"
if "%tgt%"=="" set "tgt=all"
if /i "%~1"=="start" goto cli_start
if /i "%~1"=="stop" goto cli_stop
if /i "%~1"=="restart" goto cli_restart
echo Usage: run.bat [start^|stop^|restart] [api^|web^|all]
exit /b 1

:cli_start
if /i not "%tgt%"=="web" call :start_api
if /i not "%tgt%"=="api" call :start_web
exit /b 0

:cli_stop
if /i not "%tgt%"=="web" call :stop_port %API_PORT% API
if /i not "%tgt%"=="api" call :stop_port %WEB_PORT% Web
exit /b 0

:cli_restart
call :cli_stop
call :wait
goto cli_start

:: ---------- helpers ----------

:wait
ping -n 3 127.0.0.1 >nul
exit /b 0

:isup
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul
exit /b %errorlevel%

:loadenv
rem Bootstrap admin only (see .env.example). Read from .env if it exists.
if exist "%~dp0.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0.env") do set "%%a=%%b"
)
exit /b 0

:start_api
call :isup %API_PORT% && ( echo API is already running on port %API_PORT%. & exit /b 0 )
where uv >nul 2>&1 || ( echo uv is not installed or not on PATH. & exit /b 1 )
call :loadenv
if not exist "%~dp0sage_api\.venv" (
  echo First run: installing API dependencies...
  pushd "%~dp0sage_api" & call uv sync & popd
)
start "DXC Sage API" /min /d "%~dp0sage_api" cmd /c uv run uvicorn sage.app:create_app --factory --host 127.0.0.1 --port %API_PORT%
echo API starting on http://localhost:%API_PORT% (own window, minimized).
exit /b 0

:start_web
call :isup %WEB_PORT% && ( echo Web is already running on port %WEB_PORT%. & exit /b 0 )
where pnpm >nul 2>&1 || ( echo pnpm is not installed or not on PATH. & exit /b 1 )
if not exist "%~dp0sage_web\node_modules" (
  echo First run: installing web dependencies...
  pushd "%~dp0sage_web" & call pnpm install & popd
)
start "DXC Sage Web" /min /d "%~dp0sage_web" cmd /c pnpm dev
echo Web starting on http://localhost:%WEB_PORT% (own window, minimized).
exit /b 0

:stop_port
rem %1 = port, %2 = name. Kills whatever listens on the port, with its child processes.
set "found="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
  taskkill /PID %%p /T /F >nul 2>&1
  set "found=1"
)
if defined found ( echo %~2 stopped. ) else ( echo %~2 was not running. )
exit /b 0
