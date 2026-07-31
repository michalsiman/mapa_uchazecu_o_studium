# Mapa uchazečů o studium

Tato aplikace je napsaná v Pythonu a slouží k zobrazení uchazečů o střední školu na mapě České republiky.

## Vlastnosti

- nahrání CSV souboru s řádky ve formátu `ADRESA,PSČ,POČET_UCHAZEČŮ`
- uložení nahraných souborů do lokálního pracovního adresáře
- seznam nahraných souborů s možností jejich smazání
- interaktivní mapové zobrazení s klastrováním bodů
- popisky zobrazují adresu, PSČ a počet uchazečů

## Instalace

1. Otevřete klasický příkazový řádek Windows (`cmd.exe`) v tomto adresáři.
2. Spusťte `install.cmd`, který vytvoří virtuální prostředí a nainstaluje závislosti.
3. Volitelně upravte lokální `config.ini` podle souboru `config.example.ini`. Tento lokální soubor se na GitHub neposílá.

```cmd
install.cmd
```

4. Pokud chcete instalaci provést ručně, použijte:

```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Spuštění

Po instalaci spusťte aplikaci pomocí:

```cmd
run.cmd
```

Pokud nechcete použít `run.cmd`, můžete aplikaci spustit také ručně:

```cmd
.\.venv\Scripts\activate.bat
python main.py
```

## Vytvoření EXE

Aplikaci lze zabalením do jednoho spustitelného souboru pro Windows vytvořit pomocí `PyInstaller`.

1. Nainstalujte `PyInstaller` v prostředí:

```cmd
.\.venv\Scripts\activate.bat
python -m pip install pyinstaller
```

2. Spusťte build script:

```cmd
build_exe.cmd
```

Po dokončení najdete výsledný soubor `main.exe` v podadresáři `dist\main`. Uložení a cache aplikace budou fungovat v adresáři, kde exe spustíte.

## Použití

- stiskněte tlačítko `Vybrat a nahrát CSV soubor`
- vyberte soubor s adresami, PSČ a počty uchazečů
- okno v pravé části zobrazí mapu České republiky s body a skupinami bodů
- kliknutím na bod se zobrazí detail záznamu

## Poznámky

- Adresy se převádějí na souřadnice pomocí služby Nominatim (OpenStreetMap).
- Pokud máte velký počet záznamů, geokódování může trvat déle a je cacheováno ve složce `storage`.
- Aplikace je multiplatformní a měla by fungovat na Windows, macOS i Linuxu.

## Bezpečné publikování na GitHub

- Do repozitáře se neposílá lokální `config.ini`, složka `storage` ani žádné root CSV soubory včetně `vzor_dat_z_dips.csv`.
- Díky `.gitignore` se nebudou verzovat cache soubory, nahraná data ani lokální konfigurace s adresou školy.
- Pokud by některý z těchto souborů byl už dříve přidaný do Gitu, odeberte ho z indexu před prvním pushem:

```cmd
git rm --cached config.ini
git rm --cached vzor_dat_z_dips.csv
git rm -r --cached storage
```

- Základní publikování do připraveného GitHub repozitáře z `cmd.exe`:

```cmd
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/UZIVATEL/REPOZITAR.git
git push -u origin main
```
