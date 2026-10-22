@echo off
cd /d "%~dp0"
set "SMARTHR_PY=%~dp0.venv-run\Scripts\python.exe"
if exist "%SMARTHR_PY%" goto run
set "SMARTHR_BOOT=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%SMARTHR_BOOT%" goto setup
set "SMARTHR_BOOT=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%SMARTHR_BOOT%" goto setup
where python >nul 2>nul
if not errorlevel 1 (
    set "SMARTHR_BOOT=python"
    goto setup
)
echo Python 3.12+ is required. Install Python and run this file again.
pause
exit /b 1
:setup
"%SMARTHR_BOOT%" -m venv .venv-run
if errorlevel 1 goto failed
"%SMARTHR_PY%" -m pip install -r requirements.txt -r requirements-chat.txt
if errorlevel 1 goto failed
:run
"%SMARTHR_PY%" run_smarthr.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. See the error above.
pause
exit /b 1
