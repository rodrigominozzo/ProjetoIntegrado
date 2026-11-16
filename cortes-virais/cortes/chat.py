"""Chat: leitura do replay (vídeos gravados) e acompanhamento em tempo real (lives)."""
from __future__ import annotations

import collections
import json
import logging
import re
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Reações típicas de momento viral: risada, espanto, pedido de corte.
EMPOLGACAO = re.compile(
    r"k{4,}|(ha){2,}|(rs){2,}|lol|lmao|\bclip|\bcorta|\bcorte\b|meu deus|mds|socorro|"
    r"n[aã]o acredito|que isso|absurdo|[!?]{3,}|[😂🤣😱🔥💀😭👏]",
    re.IGNORECASE,
)


def peso(texto: str) -> float:
    """Uma mensagem empolgada vale por duas; caixa alta também conta."""
    letras = [c for c in texto if c.isalpha()]
    gritando = len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) > 0.7
    return 2.0 if EMPOLGACAO.search(texto) or gritando else 1.0


def _texto(renderer: dict) -> str:
    partes = []
    for run in renderer.get("message", {}).get("runs", []):
        if "text" in run:
            partes.append(run["text"])
        elif "emoji" in run:
            emoji = run["emoji"]
            partes.append(emoji.get("emojiId", "") if len(emoji.get("emojiId", "")) <= 4
                          else (emoji.get("shortcuts") or [""])[0])
    return "".join(partes)


def ler_replay(caminho: str | Path) -> list[tuple[float, str]]:
    """Lê o live_chat.json do yt-dlp (ou um JSONL simples {"t": seg, "texto": ...})."""
    mensagens: list[tuple[float, str]] = []
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if "t" in obj:
            mensagens.append((float(obj["t"]), str(obj.get("texto", ""))))
            continue
        replay = obj.get("replayChatItemAction", {})
        t = float(replay.get("videoOffsetTimeMsec", 0)) / 1000
        for acao in replay.get("actions", []):
            item = acao.get("addChatItemAction", {}).get("item", {})
            renderer = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
            if renderer:
                mensagens.append((t, _texto(renderer)))
    mensagens.sort(key=lambda m: m[0])
    return mensagens


def trecho(mensagens: list[tuple[float, str]], inicio: float, fim: float, limite: int = 25) -> list[str]:
    return [txt for t, txt in mensagens if inicio <= t <= fim and txt][:limite]


class ChatAoVivo:
    """Lê o chat de uma live em segundo plano. Sem a biblioteca, segue só com áudio."""

    def __init__(self, url: str):
        self.url = url
        self._fila: collections.deque[tuple[float, str]] = collections.deque(maxlen=20000)
        self._trava = threading.Lock()
        self.ativo = False
        self._parar = threading.Event()

    def iniciar(self) -> None:
        threading.Thread(target=self._rodar, daemon=True, name="chat").start()

    def parar(self) -> None:
        self._parar.set()

    def _rodar(self) -> None:
        try:
            from chat_downloader import ChatDownloader
        except ImportError:
            log.warning("chat-downloader não instalado: detecção usará apenas o áudio.")
            return
        while not self._parar.is_set():
            try:
                self.ativo = True
                for msg in ChatDownloader().get_chat(self.url, message_groups=["messages", "superchat"]):
                    if self._parar.is_set():
                        break
                    with self._trava:
                        self._fila.append((time.time(), msg.get("message") or ""))
            except Exception as e:  # noqa: BLE001
                log.warning("Chat caiu (%s); reconectando em 10s.", e)
            self.ativo = False
            self._parar.wait(10)

    def desde(self, t0: float, t1: float | None = None) -> list[tuple[float, str]]:
        t1 = t1 or time.time()
        with self._trava:
            return [m for m in self._fila if t0 <= m[0] < t1]
