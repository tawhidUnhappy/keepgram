@echo off
rem keepgram on Windows: builds .venv on first run, then runs the command.
rem Double-click it for the menu, or: run.bat upload "D:\Photos"
setlocal
set "ROOT=%~dp0."
set "PY=%ROOT%\.venv\Scripts\python.exe"
set "PYTHONUTF8=1"
if exist "%PY%" goto run

echo [keepgram] setting up .venv ...
where uv >nul 2>nul
if %errorlevel%==0 (
    uv venv -q --python 3.12 "%ROOT%\.venv"
    uv pip install -q --python "%PY%" -e "%ROOT%[fast]" || uv pip install -q --python "%PY%" -e "%ROOT%"
) else (
    py -3 -m venv "%ROOT%\.venv" 2>nul || python -m venv "%ROOT%\.venv"
    "%PY%" -m pip install -q -e "%ROOT%[fast]" || "%PY%" -m pip install -q -e "%ROOT%"
)
if not exist "%PY%" (
    echo Python 3.10 or newer is needed: https://www.python.org/downloads/ ^(tick "Add to PATH"^)
    pause
    exit /b 1
)

:run
"%PY%" -m keepgram.cli %*
if "%~1"=="" pause
