"""Fila de publicação: respeita limites diários e espaçamento entre posts."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from .. import seguranca
from ..banco import Banco
from . import instagram, youtube

log = logging.getLogger(__name__)
NOMES = {"yt": "youtube", "ig": "instagram"}


def janelas(texto: str) -> list[tuple[int, int]]:
    """Converte "11:00-14:00, 18:00-23:30" em pares de minutos do dia."""
    pares = []
    for trecho in filter(None, (t.strip() for t in texto.split(","))):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", trecho)
        if not m or int(m[1]) > 23 or int(m[3]) > 24 or int(m[2]) > 59 or int(m[4]) > 59:
            raise ValueError("Escreva os horários assim: 11:00-14:00, 18:00-23:30")
        pares.append((int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])))
    return pares


def no_horario(cfg: dict, agora: float | None = None) -> bool:
    """Estamos numa das janelas de postagem? Sem janelas configuradas, sempre."""
    try:
        pares = janelas(cfg["publicar"].get("horarios", ""))
    except ValueError:
        return True
    if not pares:
        return True
    t = time.localtime(agora)
    minuto = t.tm_hour * 60 + t.tm_min
    return any(a <= minuto < b if a <= b else (minuto >= a or minuto < b) for a, b in pares)


def conectado(plataforma: str, cfg: dict) -> bool:
    """A conta de destino está configurada? Sem isso a plataforma é pulada, sem gastar tentativas."""
    if plataforma == "yt":
        return Path(cfg["publicar"]["youtube"]["token"]).exists()
    return bool(os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"))


def _texto(corte, plataforma: str) -> str:
    marcas = " ".join(f"#{h}" for h in json.loads(corte["hashtags"] or "[]"))
    if plataforma == "ig":
        return f"{corte['titulo']}\n\n{corte['descricao']}\n\n{marcas}".strip()
    return f"{corte['descricao']}\n\n{marcas}".strip()


def publicar_um(cfg: dict, banco: Banco, corte, plataforma: str) -> bool:
    """Envia um corte para uma plataforma e registra o resultado."""
    nome = NOMES[plataforma]
    cfg_p = cfg["publicar"][nome]
    try:
        if not Path(corte["arquivo"]).exists():
            raise FileNotFoundError("arquivo do corte não existe mais")
        if plataforma == "yt":
            remoto = youtube.enviar(corte["arquivo"], corte["titulo"], _texto(corte, "yt"),
                                    json.loads(corte["hashtags"] or "[]"), cfg_p,
                                    curto=corte["origem"] != "compilacao",
                                    capa=corte["capa"] or "")
            link = (f"https://youtu.be/{remoto}" if corte["origem"] == "compilacao"
                    else f"https://youtube.com/shorts/{remoto}")
        else:
            remoto, link = instagram.enviar(corte["arquivo"], _texto(corte, "ig"), cfg_p,
                                            capa_ms=corte["capa_ms"])
    except Exception as e:  # noqa: BLE001
        erro = seguranca.sem_segredos(e)
        log.error("Falha ao publicar corte %s no %s: %s", corte["id"], nome, erro)
        banco.falhou(corte["id"], plataforma, erro)
        return False
    banco.publicado(corte["id"], plataforma, remoto, link)
    log.info("Publicado no %s: %s (%s)", nome, corte["titulo"], remoto)
    return True


def publicar_pendentes(cfg: dict, banco: Banco) -> int:
    """Publica o que couber agora nos limites. Devolve quantos posts foram feitos."""
    if banco.opcao("publicacao_auto", "1") != "1":
        return 0  # pausada pelo painel
    feitos = 0
    for plataforma, nome in NOMES.items():
        cfg_p = cfg["publicar"][nome]
        if not cfg_p["ativo"] or not conectado(plataforma, cfg):
            continue
        for corte in banco.pendentes(plataforma):
            if banco.publicados_desde(plataforma, time.time() - 86400) >= cfg_p["max_por_dia"]:
                log.info("Limite diário do %s atingido; o restante fica na fila.", nome)
                break
            espacado = (time.time() - banco.ultima_publicacao(plataforma)
                        >= cfg["publicar"]["intervalo_min"] * 60)
            if not corte["urgente"] and not (espacado and no_horario(cfg)):
                continue  # cortes de live furam a fila; os demais esperam intervalo e horário
            feitos += publicar_um(cfg, banco, corte, plataforma)
    return feitos
