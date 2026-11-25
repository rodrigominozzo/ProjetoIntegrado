"""Envio para o TikTok pela Content Posting API, na modalidade "caixa de entrada".

O vídeo pronto vai para as notificações do app do TikTok da conta conectada; você abre,
confere e publica (a legenda é escrita lá, a API desta modalidade não a recebe). É a
única forma de publicar no perfil sem a auditoria do TikTok, que recusa ferramentas de
uso próprio. Limite do TikTok: no máximo 5 envios pendentes a cada 24 h por conta.

Conexão: Login Kit para computador (OAuth com PKCE, retorno para este painel em
http://localhost:PORTA/oauth/tiktok/). O acesso vale 24 h e é renovado sozinho com o
refresh token (válido por 1 ano).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)
AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
ESCOPOS = "user.info.basic,video.upload"
PEDACO_MAX = 64 * 1024 * 1024    # até isso vai inteiro; acima, em partes
PEDACO = 10 * 1024 * 1024        # partes de 10 MB (o TikTok aceita de 5 a 64 MB)
ESPERA_STATUS_S = 300


class LimiteTikTok(RuntimeError):
    """O TikTok recusou por limite (5 pendentes em 24 h, ou 6 pedidos por minuto)."""


def chaves() -> tuple[str, str]:
    return (os.environ.get("TIKTOK_CLIENT_KEY", "").strip(),
            os.environ.get("TIKTOK_CLIENT_SECRET", "").strip())


def conectado(cfg_tt: dict) -> bool:
    return all(chaves()) and Path(cfg_tt["token"]).exists()


# --- conexão da conta ----------------------------------------------------------

def iniciar_login(redirect_uri: str) -> tuple[str, str, str]:
    """Endereço da tela de autorização do TikTok, o `state` e o `code_verifier` (PKCE)."""
    client_key, _ = chaves()
    if not client_key:
        raise ValueError("Cole antes o Client Key e o Client Secret do app do TikTok.")
    estado = secrets.token_urlsafe(24)
    verificador = secrets.token_urlsafe(64)[:96]
    desafio = hashlib.sha256(verificador.encode()).hexdigest()  # o TikTok pede em hexadecimal
    url = AUTORIZAR + "?" + urlencode({
        "client_key": client_key, "scope": ESCOPOS, "response_type": "code",
        "redirect_uri": redirect_uri, "state": estado,
        "code_challenge": desafio, "code_challenge_method": "S256"})
    return url, estado, verificador


def _guardar(cfg_tt: dict, dados: dict) -> dict:
    agora = time.time()
    token = {
        "access_token": dados["access_token"], "refresh_token": dados["refresh_token"],
        "open_id": dados.get("open_id", ""), "scope": dados.get("scope", ""),
        "expira": agora + float(dados.get("expires_in", 86400)) - 300,
        "refresh_expira": agora + float(dados.get("refresh_expires_in", 31536000)),
    }
    destino = Path(cfg_tt["token"])
    destino.write_text(json.dumps(token))
    try:
        destino.chmod(0o600)
    except OSError:
        pass
    return token


def _pedir_token(campos: dict) -> dict:
    client_key, client_secret = chaves()
    r = requests.post(f"{API}/oauth/token/", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": client_key, "client_secret": client_secret, **campos})
    dados = r.json() if r.content else {}
    if r.status_code != 200 or "access_token" not in dados:
        motivo = dados.get("error_description") or dados.get("error") or f"HTTP {r.status_code}"
        raise RuntimeError(f"O TikTok recusou a autorização: {motivo}")
    return dados


def concluir_login(cfg_tt: dict, codigo: str, redirect_uri: str, verificador: str) -> None:
    dados = _pedir_token({"code": codigo, "grant_type": "authorization_code",
                          "redirect_uri": redirect_uri, "code_verifier": verificador})
    if "video.upload" not in dados.get("scope", ""):
        raise RuntimeError("A autorização veio sem a permissão de enviar vídeos (video.upload). "
                           "Confira se o produto Content Posting API está no app.")
    _guardar(cfg_tt, dados)


def _token(cfg_tt: dict) -> str:
    caminho = Path(cfg_tt["token"])
    if not caminho.exists():
        raise RuntimeError("TikTok não conectado (Configurações → Conectar o TikTok).")
    token = json.loads(caminho.read_text())
    if time.time() < token["expira"]:
        return token["access_token"]
    if time.time() >= token.get("refresh_expira", 0):
        raise RuntimeError("A conexão com o TikTok venceu; conecte de novo nas Configurações.")
    token = _guardar(cfg_tt, _pedir_token({"grant_type": "refresh_token",
                                           "refresh_token": token["refresh_token"]}))
    return token["access_token"]


def _api(cfg_tt: dict, caminho: str, corpo: dict) -> dict:
    r = requests.post(f"{API}{caminho}", json=corpo, timeout=60, headers={
        "Authorization": f"Bearer {_token(cfg_tt)}",
        "Content-Type": "application/json; charset=UTF-8"})
    dados = r.json() if r.content else {}
    erro = dados.get("error") or {}
    if r.status_code == 200 and erro.get("code", "ok") == "ok":
        return dados.get("data") or {}
    codigo = erro.get("code") or f"HTTP {r.status_code}"
    if r.status_code == 429 or codigo.startswith("spam_risk") or codigo == "rate_limit_exceeded":
        raise LimiteTikTok(f"O TikTok chegou ao limite de envios ({codigo}). Tento de novo mais tarde.")
    raise RuntimeError(f"O TikTok recusou o envio: {erro.get('message') or codigo} ({codigo})")


def usuario(cfg_tt: dict) -> dict:
    """Nome da conta conectada (para mostrar nas Configurações)."""
    r = requests.get(f"{API}/user/info/", params={"fields": "open_id,display_name,avatar_url"},
                     headers={"Authorization": f"Bearer {_token(cfg_tt)}"}, timeout=30)
    return (r.json().get("data") or {}).get("user") or {}


# --- envio -----------------------------------------------------------------------

def partes(tamanho: int) -> tuple[int, int]:
    """(tamanho de cada parte, quantidade). A última parte leva o resto (regra do TikTok)."""
    if tamanho <= PEDACO_MAX:
        return tamanho, 1
    return PEDACO, tamanho // PEDACO


def enviar(arquivo: str | Path, cfg_tt: dict, progresso=None) -> tuple[str, str]:
    """Manda o vídeo para a caixa de entrada do TikTok. Devolve (publish_id, "")."""
    progresso = progresso or (lambda etapa, fracao=None: None)
    arquivo = Path(arquivo)
    tamanho = arquivo.stat().st_size
    pedaco, total = partes(tamanho)
    progresso("Preparando o envio ao TikTok")
    dados = _api(cfg_tt, "/post/publish/inbox/video/init/", {"source_info": {
        "source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": pedaco,
        "total_chunk_count": total}})
    publish_id, destino = dados["publish_id"], dados["upload_url"]
    with open(arquivo, "rb") as f:
        for i in range(total):
            ini = i * pedaco
            fim = tamanho - 1 if i == total - 1 else ini + pedaco - 1
            f.seek(ini)
            bloco = f.read(fim - ini + 1)
            progresso("Enviando o vídeo ao TikTok", ini / tamanho)
            for tentativa in range(4):
                try:
                    r = requests.put(destino, data=bloco, timeout=300, headers={
                        "Content-Type": "video/mp4", "Content-Length": str(len(bloco)),
                        "Content-Range": f"bytes {ini}-{fim}/{tamanho}"})
                    if r.status_code in (200, 201, 206):
                        break
                    erro = f"HTTP {r.status_code}"
                except requests.RequestException as e:
                    erro = str(e)
                time.sleep(5 * (tentativa + 1))
            else:
                raise RuntimeError(f"O envio ao TikTok falhou na parte {i + 1} de {total}: {erro}")
    progresso("TikTok processando o vídeo", 1.0)
    limite = time.time() + ESPERA_STATUS_S
    while time.time() < limite:
        situacao = _api(cfg_tt, "/post/publish/status/fetch/", {"publish_id": publish_id})
        status = situacao.get("status", "")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return publish_id, ""
        if status == "FAILED":
            raise RuntimeError(f"O TikTok não aceitou o vídeo: {situacao.get('fail_reason') or 'sem motivo'}")
        time.sleep(10)  # 6 pedidos por minuto por conta: consulta a cada 10 s
    # Ainda processando: o vídeo já está com o TikTok e costuma chegar ao app em minutos.
    log.info("TikTok ainda processando %s após %d s; segue como enviado.", publish_id, ESPERA_STATUS_S)
    return publish_id, ""
