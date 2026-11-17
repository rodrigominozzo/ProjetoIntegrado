@echo off
rem Instala o Cortes Virais numa pasta isolada (.venv). Rode uma vez, com dois cliques.
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (echo Falta o ffmpeg. Instale com:  winget install Gyan.FFmpeg  e abra este instalador de novo. & (if not defined CORTES_SEM_PAUSA pause) & exit /b 1)

rem Procura um Python entre 3.10 e 3.13: versoes mais novas ainda nao tem todas as bibliotecas.
set PY=
for %%v in (3.12 3.13 3.11 3.10) do if not defined PY (py -%%v -c "" >nul 2>nul && set PY=py -%%v)
if not defined PY (python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set PY=python)
if not defined PY (
  echo Nao encontrei um Python compativel ^(3.10 a 3.13^).
  echo Instale o Python 3.12 com:  winget install Python.Python.3.12
  echo Versoes mais novas, como a 3.14 e a 3.15, ainda nao funcionam com as bibliotecas de video e voz.
  (if not defined CORTES_SEM_PAUSA pause) & exit /b 1
)
echo Usando: %PY%
%PY% -m venv .venv || ((if not defined CORTES_SEM_PAUSA pause) & exit /b 1)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt || (echo A instalacao falhou. Veja a mensagem acima. & (if not defined CORTES_SEM_PAUSA pause) & exit /b 1)
rem Opcionais: se algum falhar, o programa funciona sem ele.
for %%p in (pywebview chat-downloader faster-whisper piper-tts) do .venv\Scripts\pip install %%p || echo Aviso: %%p nao foi instalado ^(opcional^).
.venv\Scripts\python -m piper.download_voices pt_BR-faber-medium --download-dir vozes || echo Aviso: a voz da narracao nao foi baixada. Instale depois pela aba Configuracoes.
if not exist config.yaml copy config.exemplo.yaml config.yaml >nul
if not exist .env copy .env.exemplo .env >nul
echo.
echo Pronto. Abra com dois cliques em "Cortes Virais.bat".
if not defined CORTES_SEM_PAUSA pause
