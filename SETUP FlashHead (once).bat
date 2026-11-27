@echo off
rem ===========================================================================
rem  FlashHead Lip-Sync - one-time setup
rem
rem  Gets the FlashHead plugin (the server), builds its Python environment and
rem  installs the packages this app needs. Sapphire itself is NOT required.
rem
rem  Safe to run again: it only fills in what is missing.
rem ===========================================================================
title FlashHead Lip-Sync - setup
setlocal EnableExtensions
cd /d "%~dp0"

set "PLUGIN=%~dp0flashhead"
if exist "%~dp0flashhead\server.py" goto found
if exist "%~dp0sapphire-flashhead\server.py" set "PLUGIN=%~dp0sapphire-flashhead"
if exist "%~dp0sapphire-flashhead\server.py" goto found
if exist "%~dp0..\sapphire-flashhead\server.py" set "PLUGIN=%~dp0..\sapphire-flashhead"
if exist "%~dp0..\sapphire-flashhead\server.py" goto found
if exist "%~dp0..\flashhead\server.py" set "PLUGIN=%~dp0..\flashhead"
if exist "%~dp0..\flashhead\server.py" goto found

echo FlashHead plugin not found. Cloning it into:
echo    %PLUGIN%
echo.
where git >nul 2>nul
if errorlevel 1 (
    echo git is not installed. Either install git, or download the plugin by hand:
    echo    https://github.com/ddxfish/sapphire-flashhead
    echo and unpack it into: %PLUGIN%
    echo.
    pause
    exit /b 1
)
git clone https://github.com/ddxfish/sapphire-flashhead "%PLUGIN%"
if errorlevel 1 (
    echo.
    echo Clone failed - check your internet connection, then run this again.
    pause
    exit /b 1
)

:found
echo Using the FlashHead plugin at:
echo    %PLUGIN%
echo.

rem ---- find conda (a double-click has no Anaconda Prompt in the PATH) -------
set "CONDA_BASE="
if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_BASE=%USERPROFILE%\miniconda3"
if not defined CONDA_BASE if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_BASE=%USERPROFILE%\anaconda3"
if not defined CONDA_BASE if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "CONDA_BASE=%ProgramData%\miniconda3"
if not defined CONDA_BASE if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_BASE=%ProgramData%\anaconda3"
if not defined CONDA_BASE if exist "%LOCALAPPDATA%\miniconda3\Scripts\conda.exe" set "CONDA_BASE=%LOCALAPPDATA%\miniconda3"
if not defined CONDA_BASE (
    echo conda not found in the usual places.
    echo Install Miniconda, or run this from an Anaconda Prompt:
    echo    https://docs.conda.io/en/latest/miniconda.html
    echo.
    pause
    exit /b 1
)
echo conda: %CONDA_BASE%
echo.

rem ---- pick the environment: the plugin's own, if it already exists --------
set "ENV="
if exist "%CONDA_BASE%\envs\flashhead-server\python.exe" set "ENV=flashhead-server"
if not defined ENV if exist "%CONDA_BASE%\envs\sapphire-plugin-flashhead\python.exe" set "ENV=sapphire-plugin-flashhead"

if not defined ENV set "ENV=flashhead-server"
if not exist "%CONDA_BASE%\envs\%ENV%\python.exe" (
    echo Making the %ENV% environment - Python 3.10, once...
    "%CONDA_BASE%\Scripts\conda.exe" create -y -n %ENV% python=3.10
    if errorlevel 1 (
        echo.
        echo Could not create the environment. Read the message above.
        pause
        exit /b 1
    )
)

set "PY=%CONDA_BASE%\envs\%ENV%\python.exe"
if not exist "%PY%" (
    echo Environment %ENV% has no python.exe at:
    echo    %PY%
    pause
    exit /b 1
)
echo environment: %ENV%
echo.

rem ---- the server's packages: the list plugin.json already carries ----------
echo Installing the server's packages (the first time downloads ~5 GB)...
"%PY%" -c "import json; print('\n'.join(json.load(open(r'%PLUGIN%\plugin.json', encoding='utf-8'))['environment']['pip']))" > "%TEMP%\flashhead_requirements.txt"
if errorlevel 1 (
    echo Could not read %PLUGIN%\plugin.json
    pause
    exit /b 1
)
"%PY%" -m pip install -r "%TEMP%\flashhead_requirements.txt"
if errorlevel 1 (
    echo.
    echo Package install failed. Read the message above, then run this again.
    pause
    exit /b 1
)
rem same stamp the plugin's flashhead-server.bat uses, so it will not reinstall
copy /y "%TEMP%\flashhead_requirements.txt" "%CONDA_BASE%\envs\%ENV%\flashhead-requirements.txt" >nul 2>nul

rem ---- this app's own packages ---------------------------------------------
echo.
echo Installing the app's packages...
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Package install failed. Read the message above, then run this again.
    pause
    exit /b 1
)

echo.
echo ===========================================================================
echo  Setup finished.
echo.
echo  Next: run "START Lip-Sync App.bat".
echo  The first CONNECT downloads the models (~8 GB, shown in the app window)
echo  into:
echo     %PLUGIN%\user\models\flashhead
echo  Later starts take ~45 seconds to load them onto the GPU.
echo ===========================================================================
echo.
pause
