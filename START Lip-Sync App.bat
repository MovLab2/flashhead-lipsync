@echo off
title FlashHead Realtime Lip-Sync
cd /d "%~dp0"

rem Run the app with the SAME env that runs the FlashHead server: the app starts
rem server.py with this very Python, so a different interpreter would miss the
rem server's packages.
set "PY="
if exist "%USERPROFILE%\miniconda3\envs\flashhead-server\python.exe" set "PY=%USERPROFILE%\miniconda3\envs\flashhead-server\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\envs\sapphire-plugin-flashhead\python.exe" set "PY=%USERPROFILE%\miniconda3\envs\sapphire-plugin-flashhead\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\envs\flashhead-server\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\flashhead-server\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\envs\sapphire-plugin-flashhead\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\sapphire-plugin-flashhead\python.exe"
if not defined PY if exist "%ProgramData%\miniconda3\envs\flashhead-server\python.exe" set "PY=%ProgramData%\miniconda3\envs\flashhead-server\python.exe"
if not defined PY set "PY=python"

"%PY%" realtime_app.py
if errorlevel 1 (
    echo.
    echo The app stopped with an error - the message above says why.
    pause
)
