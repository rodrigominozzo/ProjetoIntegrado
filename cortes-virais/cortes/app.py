"""Programa em janela: abre o painel numa janela própria e mantém tudo rodando enquanto
ela estiver aberta. Ao fechar, guarda o que estava em andamento para retomar na próxima vez.

Ordem de tentativa para a janela:
  1. pywebview (janela nativa)            — pip install pywebview
  2. Chrome, Edge ou Chromium em modo app — janela sem abas nem barra de endereço
  3. navegador padrão                     — o programa segue rodando no terminal
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import painel
from .banco import Banco

log = logging.getLogger(__name__)
TITULO = "Cortes Virais"
AVISO_FECHAR = ("Ao fechar, o acompanhamento das lives e as análises param. "
                "O que estiver em andamento é retomado quando você abrir de novo. Fechar?")


def _ja_aberto(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/estado", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def navegador_app() -> str | None:
    """Caminho de um Chrome/Edge/Chromium instalado, para abrir em modo aplicativo."""
    nomes = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "microsoft-edge", "msedge", "chrome", "brave-browser"]
    for nome in nomes:
        achado = shutil.which(nome)
        if achado:
            return achado
    fixos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    return next((c for c in fixos if Path(c).exists()), None)


def _janela(url: str, pasta: Path) -> None:
    """Mostra a janela e só volta quando ela for fechada."""
    try:
        import webview
    except ImportError:
        webview = None
    if webview:
        webview.create_window(TITULO, url, width=1320, height=880, min_size=(900, 600),
                              confirm_close=True,
                              localization={"global.quitConfirmation": AVISO_FECHAR})
        webview.start()
        return
    navegador = navegador_app()
    if navegador:
        # Perfil próprio: o processo termina quando a janela fecha, e assim sabemos a hora de sair.
        perfil = (pasta / "janela").resolve()
        inicio = time.time()
        subprocess.run([navegador, f"--app={url}", f"--user-data-dir={perfil}",
                        "--window-size=1320,880", "--no-first-run", "--no-default-browser-check"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if time.time() - inicio > 3:
            return
        log.warning("A janela do navegador não abriu; usando o navegador padrão.")
    webbrowser.open(url)
    print(f"\n{TITULO} aberto no navegador: {url}\n"
          "Deixe esta janela do terminal aberta; para encerrar, pressione Ctrl+C.\n")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def abrir(cfg: dict, banco: Banco, caminho_cfg: str = "config.yaml", porta: int = 8000) -> None:
    pasta = Path(cfg["pasta_trabalho"])
    arquivo_log = logging.FileHandler(pasta / "cortes.log", encoding="utf-8")
    arquivo_log.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(arquivo_log)

    if _ja_aberto(porta):  # já existe um programa rodando: só mostra a janela dele
        log.info("%s já está rodando; abrindo a janela.", TITULO)
        _janela(f"http://127.0.0.1:{porta}/", pasta)
        return
    try:
        servidor, ger = painel.criar(cfg, banco, "127.0.0.1", porta, caminho_cfg)
    except OSError:  # porta ocupada por outro programa: usa uma livre
        servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, caminho_cfg)
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    threading.Thread(target=servidor.serve_forever, daemon=True, name="painel").start()
    log.info("%s em %s", TITULO, url)
    try:
        _janela(url, pasta)
    finally:
        log.info("Encerrando: %d tarefas serão retomadas na próxima abertura.", ger.ativos())
        ger.encerrar()
        servidor.shutdown()
        time.sleep(1.5)  # dá tempo de as capturas fecharem os arquivos


if __name__ == "__main__":
    sys.exit("Use: python -m cortes app")
