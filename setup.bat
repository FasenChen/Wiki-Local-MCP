@echo off
setlocal DisableDelayedExpansion
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if not errorlevel 1 (
        set "WIKI_PY=py"
        set "WIKI_PY_ARGS=-3"
        goto run
    )
)
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
    if not errorlevel 1 (
        set "WIKI_PY=python"
        set "WIKI_PY_ARGS="
        goto run
    )
)
echo Python 3.10 or newer is required. Install it and run setup again.
pause
exit /b 1

:run
%WIKI_PY% %WIKI_PY_ARGS% "%~dp0scripts\install.py"
set "WIKI_EXIT=%ERRORLEVEL%"
set "WIKI_CHOICE="
set /p "WIKI_CHOICE=Press E to edit configuration, or Enter to exit: "
if /I "%WIKI_CHOICE%"=="E" (
    %WIKI_PY% %WIKI_PY_ARGS% "%~dp0scripts\install.py" --edit
)
exit /b %WIKI_EXIT%
