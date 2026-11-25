"""Publicação de Reels pela Instagram Graph API (upload retomável, sem hospedar o arquivo).

Requer conta Instagram profissional e, no .env, IG_USER_ID e IG_ACCESS_TOKEN
(token de longa duração com instagram_content_publish).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
ESPERA_ENTRE_S = 30     # pausa antes da 2ª versão (a 3ª espera o dobro)


class FalhaProcessamento(RuntimeError):
    """O Instagram recebeu o vídeo mas não conseguiu processá-lo (ProcessingFailedError ou
    status ERROR). Costuma passar numa nova tentativa com um contêiner novo."""


def _checar(r: requests.Response) -> dict:
    try:
        dados = r.json()
    except ValueError:
        r.raise_for_status()
        raise
    if r.status_code >= 400 or "error" in dados or "debug_info" in dados:
        erro = dados.get("error") or dados.get("debug_info") or dados
        tipo = erro.get("type", "") if isinstance(erro, dict) else ""
        if tipo == "ProcessingFailedError":
            raise FalhaProcessamento("O Instagram não conseguiu processar o vídeo (falha do lado "
                                     "deles), nem em versões mais leves.")
        raise RuntimeError(f"Instagram: {erro.get('message', erro) if isinstance(erro, dict) else erro}")
    return dados


class _LeitorComProgresso:
    """Arquivo que avisa quanto já foi lido (= enviado) enquanto o requests o transmite."""

    def __init__(self, arquivo, tamanho: int, aviso) -> None:
        self._f, self._tamanho, self._aviso, self._lidos = arquivo, tamanho, aviso, 0

    def __len__(self) -> int:
        return self._tamanho

    def read(self, n: int = -1) -> bytes:
        bloco = self._f.read(n)
        self._lidos += len(bloco)
        self._aviso(min(1.0, self._lidos / max(1, self._tamanho)))
        return bloco


# Versões do vídeo, da melhor para a mais "à prova de falha". O Instagram às vezes recusa um
# vídeo dentro da especificação (ProcessingFailedError), mais nos longos; um arquivo mais
# simples e menor costuma passar. (sufixo, perfil, nível, largura, altura, taxa)
VERSOES = [
    ("ig", "high", "4.1", 1080, 1920, None),     # qualidade cheia (CRF 23, até 6 Mb/s)
    ("ig2", "main", "4.0", 1080, 1920, "4M"),    # perfil Main, taxa estável
    ("ig3", "main", "3.1", 720, 1280, "2500k"),  # 720p leve: arquivo bem menor
]


def versao_reels(arquivo: str | Path, versao: int = 0) -> Path:
    """Cópia do corte dentro da especificação de Reels da Meta: H.264, 4:2:0, quadro-chave a
    cada 2 s (GOP fechado), 30 fps constantes, áudio AAC-LC 48 kHz estéreo de 128 kbps e o
    índice (moov) no começo. Feita uma vez por versão e guardada ao lado do corte."""
    sufixo, perfil, nivel, largura, altura, taxa = VERSOES[versao]
    origem = Path(arquivo)
    destino = origem.with_suffix(f".{sufixo}.mp4")
    if destino.exists() and destino.stat().st_mtime >= origem.stat().st_mtime:
        return destino
    temporario = origem.with_suffix(f".{sufixo}.tmp.mp4")
    qualidade = (["-crf", "23", "-maxrate", "6M", "-bufsize", "12M"] if taxa is None else
                 ["-b:v", taxa, "-maxrate", taxa, "-bufsize", taxa])
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(origem),
         "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
         "-c:v", "libx264", "-preset", "veryfast", "-profile:v", perfil, "-level", nivel,
         "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60", "-sc_threshold", "0",
         "-flags", "+cgop", *qualidade,
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
         "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-movflags", "+faststart", str(temporario)], check=True)
    temporario.replace(destino)
    return destino


def _publicar(arquivo: Path, legenda: str, capa_ms: int | None, grafo: str, versao: str,
              usuario: str, token: str, progresso) -> tuple[str, str]:
    # 1. Cria o contêiner do Reel.
    dados = {"media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
             "share_to_feed": "true", "access_token": token}
    if capa_ms is not None:
        dados["thumb_offset"] = str(capa_ms)  # quadro do vídeo usado como capa
    conteiner = _checar(requests.post(f"{grafo}/{usuario}/media", timeout=60, data=dados))
    cid = conteiner["id"]
    destino = conteiner.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{versao}/{cid}"

    # 2. Envia os bytes do vídeo.
    tamanho = arquivo.stat().st_size
    progresso("Enviando o vídeo", 0.0)
    with open(arquivo, "rb") as f:
        corpo = _LeitorComProgresso(f, tamanho, lambda fr: progresso("Enviando o vídeo", fr))
        _checar(requests.post(destino, data=corpo, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho),
            "Content-Length": str(tamanho)}))

    # 3. Espera o processamento e publica.
    progresso("Processando no Instagram", None)
    for _ in range(60):
        estado = _checar(requests.get(f"{grafo}/{cid}", timeout=30, params={
            "fields": "status_code,status", "access_token": token}))
        if estado.get("status_code") == "FINISHED":
            break
        if estado.get("status_code") == "ERROR":
            raise FalhaProcessamento(f"O Instagram não conseguiu processar o vídeo: {estado.get('status')}")
        if estado.get("status_code") == "EXPIRED":
            raise RuntimeError(f"Instagram recusou o vídeo: {estado.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram não terminou de processar o vídeo em 5 minutos.")
    progresso("Publicando", None)
    publicado = _checar(requests.post(f"{grafo}/{usuario}/media_publish", timeout=60, data={
        "creation_id": cid, "access_token": token}))
    try:
        link = _checar(requests.get(f"{grafo}/{publicado['id']}", timeout=30, params={
            "fields": "permalink", "access_token": token})).get("permalink", "")
    except Exception:  # noqa: BLE001 — o post já saiu; o link é só conveniência
        link = ""
    return publicado["id"], link


def enviar(arquivo: str | Path, legenda: str, cfg_ig: dict,
           capa_ms: int | None = None, progresso=None) -> tuple[str, str]:
    """Publica o Reel e devolve (id, link). `progresso(etapa, fração)` acompanha as etapas."""
    progresso = progresso or (lambda etapa, fracao=None: None)
    usuario, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not usuario or not token:
        raise RuntimeError("Defina IG_USER_ID e IG_ACCESS_TOKEN no .env.")
    versao = cfg_ig["versao_api"]
    grafo = f"https://graph.facebook.com/{versao}"
    # Cada nova tentativa usa um contêiner novo e uma versão mais simples do vídeo, com uma
    # pausa crescente: insistir na hora com o mesmo arquivo quase nunca passa.
    for n in range(len(VERSOES)):
        progresso("Preparando o vídeo para o Instagram", None)
        try:
            pronto = versao_reels(arquivo, n)
        except (subprocess.CalledProcessError, OSError) as e:  # sem ffmpeg ou falha: manda o original
            log.warning("Não deu para preparar a versão %d do Instagram (%s); enviando o original.", n + 1, e)
            pronto = Path(arquivo)
        try:
            resultado = _publicar(pronto, legenda, capa_ms, grafo, versao, usuario, token, progresso)
            if n:
                log.info("Instagram aceitou a versão %d (%s) do vídeo.", n + 1, VERSOES[n][0])
            return resultado
        except FalhaProcessamento:
            if n + 1 == len(VERSOES):
                raise
            espera = ESPERA_ENTRE_S * (n + 1)
            log.warning("Instagram falhou ao processar o vídeo; tentando a versão %d em %d s.", n + 2, espera)
            progresso("O Instagram falhou ao processar; tentando uma versão mais leve", None)
            time.sleep(espera)
    raise RuntimeError("Instagram: envio não concluído.")
