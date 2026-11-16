"""Publicação de Reels pela Instagram Graph API (upload retomável, sem hospedar o arquivo).

Requer conta Instagram profissional e, no .env, IG_USER_ID e IG_ACCESS_TOKEN
(token de longa duração com instagram_content_publish).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests


def _checar(r: requests.Response) -> dict:
    try:
        dados = r.json()
    except ValueError:
        r.raise_for_status()
        raise
    if r.status_code >= 400 or "error" in dados:
        erro = dados.get("error", dados)
        raise RuntimeError(f"Instagram: {erro.get('message', erro) if isinstance(erro, dict) else erro}")
    return dados


def enviar(arquivo: str | Path, legenda: str, cfg_ig: dict) -> str:
    usuario, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if not usuario or not token:
        raise RuntimeError("Defina IG_USER_ID e IG_ACCESS_TOKEN no .env.")
    versao = cfg_ig["versao_api"]
    grafo = f"https://graph.facebook.com/{versao}"

    # 1. Cria o contêiner do Reel.
    conteiner = _checar(requests.post(f"{grafo}/{usuario}/media", timeout=60, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": legenda[:2200],
        "share_to_feed": "true", "access_token": token}))
    cid = conteiner["id"]
    destino = conteiner.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{versao}/{cid}"

    # 2. Envia os bytes do vídeo.
    tamanho = Path(arquivo).stat().st_size
    with open(arquivo, "rb") as f:
        _checar(requests.post(destino, data=f, timeout=600, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho)}))

    # 3. Espera o processamento e publica.
    for _ in range(60):
        estado = _checar(requests.get(f"{grafo}/{cid}", timeout=30, params={
            "fields": "status_code,status", "access_token": token}))
        if estado.get("status_code") == "FINISHED":
            break
        if estado.get("status_code") in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram recusou o vídeo: {estado.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram não terminou de processar o vídeo em 5 minutos.")
    publicado = _checar(requests.post(f"{grafo}/{usuario}/media_publish", timeout=60, data={
        "creation_id": cid, "access_token": token}))
    return publicado["id"]
