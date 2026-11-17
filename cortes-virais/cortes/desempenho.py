"""Desempenho dos cortes publicados: coleta visualizações e as devolve à IA como referência.

O que funcionou (e o que não funcionou) no próprio canal vale mais do que regra genérica:
os títulos e ganchos mais e menos vistos entram no pedido de avaliação dos próximos cortes.
"""
from __future__ import annotations

import logging
import os
import time

import requests

from . import seguranca
from .banco import Banco

log = logging.getLogger(__name__)
MINIMO_PARA_APRENDER = 8


def _youtube(ids: list[str], cfg: dict) -> dict[str, tuple[int, int]]:
    from googleapiclient.discovery import build

    from .publicar import youtube

    yt = build("youtube", "v3", credentials=youtube._credenciais(cfg["publicar"]["youtube"]),
               cache_discovery=False)
    medidas = {}
    for i in range(0, len(ids), 50):
        resposta = yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
        for item in resposta.get("items", []):
            e = item.get("statistics", {})
            medidas[item["id"]] = (int(e.get("viewCount", 0)), int(e.get("likeCount", 0)))
    return medidas


def _instagram(ids: list[str], cfg: dict) -> dict[str, tuple[int, int]]:
    token = os.environ.get("IG_ACCESS_TOKEN")
    grafo = f"https://graph.facebook.com/{cfg['publicar']['instagram']['versao_api']}"
    medidas = {}
    for mid in ids:
        r = requests.get(f"{grafo}/{mid}/insights", timeout=30,
                         params={"metric": "views,likes", "access_token": token}).json()
        valores = {d["name"]: d["values"][0]["value"] for d in r.get("data", [])}
        if valores:
            medidas[mid] = (int(valores.get("views", 0)), int(valores.get("likes", 0)))
    return medidas


def atualizar(cfg: dict, banco: Banco) -> int:
    """Atualiza visualizações e curtidas dos cortes publicados. Devolve quantos foram medidos."""
    from . import publicar

    total = 0
    for plataforma, coletar in (("yt", _youtube), ("ig", _instagram)):
        ids = banco.ids_publicados(plataforma)
        if not ids or not publicar.conectado(plataforma, cfg):
            continue
        try:
            for remoto, (vistas, curtidas) in coletar(ids, cfg).items():
                banco.medir(plataforma, remoto, vistas, curtidas)
                total += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Não foi possível medir o desempenho no %s: %s", publicar.NOMES[plataforma],
                        seguranca.sem_segredos(e))
    return total


def referencias(banco: Banco) -> str:
    """Texto para a IA com os cortes mais e menos vistos do canal (vazio se há poucos dados)."""
    medidos = [c for c in banco.cortes_medidos() if time.time() - c["publicado"] > 86400]
    if len(medidos) < MINIMO_PARA_APRENDER:
        return ""
    medidos.sort(key=lambda c: c["vistas"], reverse=True)

    def linha(c) -> str:
        gancho = f' | gancho: "{c["gancho"]}"' if c["gancho"] else ""
        return f'- {c["vistas"]} visualizações | título: "{c["titulo"]}"{gancho}'

    melhores = "\n".join(linha(c) for c in medidos[:5])
    piores = "\n".join(linha(c) for c in medidos[-3:])
    return ("Desempenho real dos cortes já publicados neste canal (use como referência do que "
            f"o público dele responde, sem copiar):\nMais vistos:\n{melhores}\nMenos vistos:\n{piores}")
