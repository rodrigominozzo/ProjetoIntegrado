"""Narração de abertura: uma frase do próprio canal, dita por voz sintética local (Piper).

É a contribuição original do canal sobre o trecho — contexto e um olhar próprio — falada
nos primeiros segundos, com o áudio original abaixado. A voz roda no seu computador, sem
conta nem custo. Baixe uma voz uma vez:

    pip install piper-tts
    python -m piper.download_voices pt_BR-faber-medium --download-dir vozes
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from . import fontes

log = logging.getLogger(__name__)
MAX_SEGUNDOS = 6.0


def instalado() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def disponivel(cfg: dict) -> bool:
    n = cfg["narracao"]
    return bool(n["ativa"] and instalado() and Path(n["voz"]).exists())


def sintetizar(texto: str, destino: Path, cfg: dict) -> float | None:
    """Gera o WAV da narração. Devolve a duração em segundos, ou None se não foi possível."""
    texto = " ".join(texto.split())
    if not texto or not disponivel(cfg):
        return None
    n = cfg["narracao"]
    try:
        subprocess.run(
            [sys.executable, "-m", "piper", "-m", n["voz"], "-f", str(destino),
             "--length-scale", f"{1 / max(0.5, min(2.0, n['velocidade'])):.2f}"],
            input=texto, text=True, check=True, capture_output=True, timeout=120)
        duracao = fontes.duracao_arquivo(destino)
    except Exception as e:  # noqa: BLE001 — narração nunca deve derrubar o corte
        log.warning("Narração não gerada (%s); o corte segue sem ela.", e)
        return None
    if duracao > MAX_SEGUNDOS:
        log.info("Narração longa demais (%.1f s); descartada.", duracao)
        return None
    return duracao
