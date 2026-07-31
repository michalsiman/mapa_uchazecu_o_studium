@echo off
pushd "%~dp0"
setlocal enabledelayedexpansion
if not exist .venv (
    python -m venv .venv
    if errorlevel 1 (
        echo Chyba: nepodarilo se vytvorit virtualni prostredi.
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
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Chyba: nepodarilo se aktualizovat pip.
    popd
    exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Chyba: nepodarilo se nainstalovat zavislosti.
    popd
    exit /b 1
)
echo Instalace dokoncena.
endlocal
popd
