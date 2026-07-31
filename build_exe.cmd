@echo off
pushd "%~dp0"
call .\.venv\Scripts\activate.bat
if errorlevel 1 (
    echo Chyba: nepodarilo se aktivovat virtuani prostredi.
    popd
    exit /b 1
)
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo Chyba: nepodarilo se nainstalovat PyInstaller.
    popd
    exit /b 1
)
pyinstaller --onefile --windowed main.py
if errorlevel 1 (
    echo Chyba: PyInstaller build selhal.
    popd
    exit /b 1
)
echo EXE bylo vytvoreno. Najdete ho v dist\main.exe
popd
