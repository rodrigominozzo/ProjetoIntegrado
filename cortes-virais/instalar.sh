#!/usr/bin/env bash
# Instala o Cortes Virais numa pasta isolada (.venv). Rode uma vez: ./instalar.sh
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo "Falta o ffmpeg. macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg"; exit 1; }
PY=""
for v in python3.12 python3.13 python3.11 python3.10 python3 python; do
  if command -v "$v" >/dev/null && "$v" -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)'; then PY=$v; break; fi
done
[ -n "$PY" ] || { echo "Preciso de um Python entre 3.10 e 3.13 (versões mais novas ainda não têm todas as bibliotecas)."; exit 1; }
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
# Opcionais: se algum falhar, o programa funciona sem ele.
for pacote in pywebview chat-downloader faster-whisper piper-tts; do
  .venv/bin/pip install "$pacote" || echo "Aviso: $pacote não foi instalado (opcional)."
done
.venv/bin/python -m piper.download_voices pt_BR-faber-medium --download-dir vozes || echo "Aviso: a voz da narração não foi baixada; instale depois pela aba Configurações."
[ -f config.yaml ] || cp config.exemplo.yaml config.yaml
[ -f .env ] || cp .env.exemplo .env
chmod +x "Cortes Virais.command" cortes-virais.sh 2>/dev/null || true
echo; echo "Pronto. Abra com: ./cortes-virais.sh  (no macOS, dois cliques em 'Cortes Virais.command')"
