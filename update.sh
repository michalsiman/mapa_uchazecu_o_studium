#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "==> Zahazuji lokální změny verzovaných souborů..."
git checkout -- .

echo "==> Stahuji změny z GitHubu..."
git pull

echo "==> Aktualizuji závislosti..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Hotovo. Aplikaci spustíš přes ./run.sh nebo: source .venv/bin/activate && python main.py"