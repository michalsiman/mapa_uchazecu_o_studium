@echo off
pushd "%~dp0"
if not exist .venv (
    echo Virtualni prostredi nenalezeno, spoustim install.cmd...
    call install.cmd
    if errorlevel 1 (
        echo Chyba: instalace se nepodarila.
        popd
        exit /b 1
    )
)
call .\.venv\Scripts\activate.bat
if errorlevel 1 (
    echo Chyba: nepodarilo se aktivovat virtualni prostredi.
    popd
    exit /b 1
)
set "retry=0"
:run_main
python main.py
if not errorlevel 1 goto run_done
if "%retry%"=="0" (
    echo Spusteni selhalo. Pokusuji se nainstalovat zavislosti a znovu spustit aplikaci...
    call install.cmd
    if errorlevel 1 (
        echo Chyba: instalace se nepodarila.
        popd
        exit /b 1
    )
    set "retry=1"
    goto run_main
)
echo Chyba: aplikaci se nepodarilo spustit i po instalaci.
:run_done
popd
