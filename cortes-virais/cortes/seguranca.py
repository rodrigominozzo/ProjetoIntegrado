"""Proteções reunidas num só lugar: o que entra de fora é tratado como não confiável.

Entradas não confiáveis neste programa: links colados, títulos e descrições de vídeos,
mensagens de chat, transcrições, respostas da IA (que leram tudo isso) e qualquer
requisição que chegue ao painel.
"""
from __future__ import annotations

import hmac
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

# Só estes sites são baixados. Sem isso, um link poderia apontar para a rede interna.
SITES_PERMITIDOS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "twitch.tv", "kick.com")
EXTENSOES_DE_VIDEO = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".ts", ".m4v"}
TAMANHO_MAXIMO_PEDIDO = 2 * 1024 * 1024  # bytes


def validar_link(alvo: str) -> str:
    """Aceita apenas http(s) para os sites permitidos. Devolve o link limpo."""
    partes = urlsplit(alvo.strip())
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        raise ValueError("O link precisa começar com https://")
    host = partes.hostname.lower().rstrip(".")
    if partes.username or partes.password:
        raise ValueError("Link inválido.")
    if not any(host == s or host.endswith("." + s) for s in SITES_PERMITIDOS):
        raise ValueError("Só são aceitos links do YouTube, da Twitch e do Kick.")
    return alvo.strip()


def validar_arquivo(alvo: str) -> str:
    """Arquivo de vídeo local: precisa existir, ser arquivo comum e ter extensão de vídeo.
    Devolve o caminho absoluto (assim nunca começa com '-', que o ffmpeg leria como opção)."""
    p = Path(alvo.strip().strip('"')).expanduser()
    if not p.is_file() or p.suffix.lower() not in EXTENSOES_DE_VIDEO:
        raise ValueError("Isso não é um link nem um arquivo de vídeo que exista neste computador.")
    return str(p.resolve())


def nome_seguro(texto: str, limite: int = 80) -> str:
    """Identificador que pode virar nome de pasta e entrar em listas do ffmpeg."""
    limpo = re.sub(r"[^\w.-]+", "_", texto, flags=re.UNICODE).strip("._")
    return (limpo or "sem_nome")[:limite]


_SEGREDO = re.compile(r"((?:access_token|key|token|api_key|client_secret|code)=)[^&\s\"']+", re.I)
_CHAVE = re.compile(r"\b(sk-ant-[\w-]{6})[\w-]+|\b(EAA[\w]{6})[\w]+|\b(AIza[\w-]{4})[\w-]+")


def sem_segredos(texto: str) -> str:
    """Tira chaves e tokens de mensagens de erro antes de gravar ou mostrar."""
    texto = _SEGREDO.sub(r"\1***", str(texto))
    return _CHAVE.sub(lambda m: next(g for g in m.groups() if g) + "***", texto)


_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|gg|tv|me|ly|xyz|br)(?:\.[a-z]{2,3})?(?:/\S*)?",
                   re.I)


def sem_links(texto: str) -> str:
    """Remove endereços de textos escritos pela IA. A IA lê chat e transcrição, que qualquer
    pessoa pode manipular; um link plantado ali não pode chegar à publicação."""
    return re.sub(r"\s{2,}", " ", _LINK.sub("", texto)).strip()


def host_local(host: str) -> bool:
    """O endereço é este próprio computador?"""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def eh_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def host_do_pedido(cabecalho: str) -> str:
    """Nome do host do cabeçalho Host, sem a porta."""
    cabecalho = (cabecalho or "").strip()
    if cabecalho.startswith("["):  # IPv6
        return cabecalho[1:cabecalho.find("]")]
    return cabecalho.rsplit(":", 1)[0] if ":" in cabecalho else cabecalho


def senha_confere(recebida: str, esperada: str) -> bool:
    return hmac.compare_digest(recebida.encode(), esperada.encode())


CABECALHOS = {
    # A página só carrega recursos do próprio painel e não pode ser embutida em outro site.
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                "media-src 'self'; connect-src 'self'; object-src 'none'; "
                                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}
