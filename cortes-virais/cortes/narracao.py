"""Narração de abertura: uma frase do próprio canal, dita por voz sintética local (Piper).

É a contribuição original do canal sobre o trecho — contexto e um olhar próprio — falada
nos primeiros segundos, com o áudio original abaixado. A voz roda no seu computador, sem
conta nem custo. Baixe uma voz uma vez:

    pip install piper-tts
    python -m piper.download_voices pt_BR-faber-medium --download-dir vozes
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

from . import fontes

log = logging.getLogger(__name__)
MAX_SEGUNDOS = 6.0


def instalado() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


instalacao = {"estado": "parada", "mensagem": ""}  # acompanhada pelo painel


def instalar_voz(cfg: dict) -> None:
    """Instala o Piper e baixa a voz configurada. Roda em segundo plano; o andamento
    fica em `instalacao`."""
    destino = Path(cfg["narracao"]["voz"])
    nome = destino.stem  # ex.: pt_BR-faber-medium
    try:
        if not re.fullmatch(r"[A-Za-z]{2}_[A-Za-z]{2}-\w+-\w+", nome) or destino.suffix != ".onnx":
            raise RuntimeError("O arquivo da voz deve ter um nome como vozes/pt_BR-faber-medium.onnx.")
        if sys.version_info[:2] > (3, 13):
            raise RuntimeError(
                f"Este programa está rodando no Python {sys.version_info.major}."
                f"{sys.version_info.minor}, novo demais para a biblioteca de voz. Instale o "
                "Python 3.12 e rode o instalador de novo.")
        instalacao.update(estado="rodando", mensagem="Instalando a biblioteca de voz…")
        if not instalado():
            subprocess.run([sys.executable, "-m", "pip", "install", "piper-tts"], check=True,
                           capture_output=True, text=True, timeout=900)
        instalacao["mensagem"] = "Baixando a voz (cerca de 60 MB)…"
        destino.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "piper.download_voices", nome, "--download-dir",
                        str(destino.parent)], check=True, capture_output=True, text=True,
                       timeout=1800)
        if not destino.exists():
            raise RuntimeError("O download terminou, mas o arquivo da voz não apareceu.")
        instalacao.update(estado="pronta", mensagem="Voz instalada.")
    except subprocess.CalledProcessError as e:
        ultimo = (e.stderr or e.stdout or "").strip().splitlines()[-1:] or ["erro desconhecido"]
        instalacao.update(estado="erro", mensagem=f"Não foi possível instalar: {ultimo[0][:200]}")
    except Exception as e:  # noqa: BLE001
        instalacao.update(estado="erro", mensagem=str(e)[:300])


def disponivel(cfg: dict) -> bool:
    n = cfg["narracao"]
    if not n["ativa"]:
        return False
    if n["motor"] == "elevenlabs":
        return bool(os.environ.get("ELEVENLABS_API_KEY") and n["voz_elevenlabs"])
    return instalado() and Path(n["voz"]).exists()


def _piper(texto: str, destino: Path, n: dict) -> None:
    subprocess.run(
        [sys.executable, "-m", "piper", "-m", n["voz"], "-f", str(destino),
         "--length-scale", f"{1 / max(0.5, min(2.0, n['velocidade'])):.2f}"],
        input=texto, text=True, check=True, capture_output=True, timeout=120)


def _elevenlabs(texto: str, destino: Path, n: dict) -> None:
    """Voz mais natural, paga por uso. Requer ELEVENLABS_API_KEY e o ID de uma voz."""
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{n['voz_elevenlabs']}", timeout=60,
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": texto, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.4, "similarity_boost": 0.8,
                                 "speed": max(0.7, min(1.2, n["velocidade"]))}})
    r.raise_for_status()
    destino.write_bytes(r.content)  # MP3; o ffmpeg lê pelo conteúdo, não pela extensão


def sintetizar(texto: str, destino: Path, cfg: dict) -> float | None:
    """Gera o áudio da fala. Devolve a duração em segundos, ou None se não foi possível."""
    texto = " ".join(texto.split())
    if not texto or not disponivel(cfg):
        return None
    n = cfg["narracao"]
    try:
        (_elevenlabs if n["motor"] == "elevenlabs" else _piper)(texto, destino, n)
        duracao = fontes.duracao_arquivo(destino)
    except Exception as e:  # noqa: BLE001 — narração nunca deve derrubar o corte
        log.warning("Narração não gerada (%s); o corte segue sem ela.", e)
        return None
    if duracao > MAX_SEGUNDOS:
        log.info("Narração longa demais (%.1f s); descartada.", duracao)
        return None
    return duracao


def preparar(c: dict, base: Path, inicio: float, cfg: dict) -> tuple[list[dict], dict | None]:
    """Sintetiza as falas de um corte. Devolve (narrações, encerramento) prontos para o render;
    `inicio` é o começo do corte no arquivo de origem."""
    if not disponivel(cfg):
        return [], None
    n = cfg["narracao"]
    comum = {"volume": n["volume"], "fundo": n["fundo"]}
    falas = []
    for k, fala in enumerate((c.get("narracoes") or [])[: n["max_falas"]]):
        arq = base.with_suffix(f".fala{k}.wav")
        dur = sintetizar(fala["texto"], arq, cfg)
        if dur:
            falas.append({**comum, "arquivo": arq, "duracao": dur, "texto": fala["texto"],
                          "t": None if fala["segundo"] < 0.6 else inicio + fala["segundo"]})
    final = None
    if n["encerramento"] and c.get("comentario_final"):
        arq = base.with_suffix(".final.wav")
        dur = sintetizar(c["comentario_final"], arq, cfg)
        if dur:
            final = {**comum, "arquivo": arq, "duracao": dur, "texto": c["comentario_final"]}
    return falas, final
