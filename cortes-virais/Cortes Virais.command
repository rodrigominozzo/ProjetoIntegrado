#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Rode ./instalar.sh primeiro."; exit 1; }
exec .venv/bin/python -m cortes app
