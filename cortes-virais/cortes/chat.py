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


def id_do_video(alvo: str) -> str:
    """Aceita o ID de 11 caracteres ou um link do YouTube (watch?v=, youtu.be/, /live/)."""
    if re.fullmatch(r"[\w-]{11}", alvo or ""):
        return alvo
    m = re.search(r"(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([\w-]{11})", alvo or "")
    if not m:
        raise ValueError("Não reconheci o vídeo do chat.")
    return m.group(1)


def _mensagens_das_acoes(acoes: list, chegada: float | None = None) -> list[tuple[float, str]]:
    """(instante, texto) das mensagens comuns e Super Chats. Com `chegada`, todas recebem
    esse instante: o YouTube entrega o chat em lotes a cada ~5 s e a detecção lê só o que
    chegou desde a última leitura, então o horário de envio faria parte do lote se perder.
    Sem ele (as mensagens antigas que vêm ao abrir o chat), vale o horário de envio."""
    saida = []
    for acao in acoes or []:
        item = acao.get("addChatItemAction", {}).get("item", {})
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            continue
        t = chegada
        if t is None:
            try:
                t = min(int(r.get("timestampUsec", 0)) / 1e6, time.time()) or time.time()
            except (TypeError, ValueError):
                t = time.time()
        saida.append((t, _texto(r)))
    return saida


class ChatAoVivo:
    """Lê o chat de uma live em segundo plano, direto do YouTube (o mesmo caminho do chat
    em janela separada). Se o chat estiver desligado ou cair, a detecção segue só com o
    áudio e ele tenta de novo depois.

    A biblioteca chat-downloader deixou de entender a página do YouTube (nov/2026: "Unable
    to parse initial video data"), por isso a leitura agora é feita aqui.
    """

    PAGINA = "https://www.youtube.com/live_chat?is_popout=1&v={}"
    API = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?prettyPrint=false"
    NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
                 "Gecko) Chrome/130.0 Safari/537.36")

    def __init__(self, url: str):
        self.url = url
        self._fila: collections.deque[tuple[float, str]] = collections.deque(maxlen=20000)
        self._trava = threading.Lock()
        self.ativo = False
        self.erro = ""
        self._parar = threading.Event()

    def iniciar(self) -> None:
        threading.Thread(target=self._rodar, daemon=True, name="chat").start()

    def parar(self) -> None:
        self._parar.set()

    def _guardar(self, mensagens: list[tuple[float, str]]) -> None:
        with self._trava:
            self._fila.extend(mensagens)

    def _rodar(self) -> None:
        espera = 10
        while not self._parar.is_set():
            try:
                self._ler()
                espera = 10
            except Exception as e:  # noqa: BLE001
                self.erro = str(e)
                log.warning("Chat caiu (%s); reconectando em %d s.", e, espera)
            self.ativo = False
            self._parar.wait(espera)
            espera = min(espera * 2, 120)

    def _ler(self) -> None:
        import requests

        vid = id_do_video(self.url)
        s = requests.Session()
        s.headers.update({"User-Agent": self.NAVEGADOR, "Accept-Language": "pt-BR,pt;q=0.9"})
        s.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")
        html = s.get(self.PAGINA.format(vid), timeout=20).text
        versao = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
        dados = re.search(r'(?:window\["ytInitialData"\]|ytInitialData)\s*=\s*(\{.+?\})\s*;\s*</script>',
                          html, re.S)
        if not versao or not dados:
            raise RuntimeError("o chat desta live está desligado ou indisponível")
        chat = json.loads(dados.group(1)).get("contents", {}).get("liveChatRenderer")
        if not chat or not chat.get("continuations"):
            raise RuntimeError("o chat desta live está desligado ou indisponível")
        self._guardar(_mensagens_das_acoes(chat.get("actions")))
        token = next(iter(chat["continuations"][0].values()))["continuation"]
        contexto = {"client": {"clientName": "WEB", "clientVersion": versao.group(1)}}
        self.ativo, self.erro = True, ""
        while not self._parar.is_set():
            r = s.post(self.API, json={"context": contexto, "continuation": token}, timeout=20)
            r.raise_for_status()
            cont = r.json().get("continuationContents", {}).get("liveChatContinuation")
            if not cont or not cont.get("continuations"):
                raise RuntimeError("a live terminou ou o chat foi fechado")
            self._guardar(_mensagens_das_acoes(cont.get("actions"), time.time()))
            prox = next(iter(cont["continuations"][0].values()))
            token = prox["continuation"]
            self._parar.wait(min(max(prox.get("timeoutMs", 5000) / 1000, 1.0), 10.0))

    def desde(self, t0: float, t1: float | None = None) -> list[tuple[float, str]]:
        t1 = t1 or time.time()
        with self._trava:
            return [m for m in self._fila if t0 <= m[0] < t1]


class ChatTwitch(ChatAoVivo):
    """Chat de uma live da Twitch. Ele é aberto: dá para ler sem conta, entrando no IRC da
    Twitch com um apelido anônimo ("justinfan" + número), como fazem os leitores de chat."""

    SERVIDOR = ("irc.chat.twitch.tv", 6667)

    def __init__(self, canal: str):
        super().__init__(canal)
        self.canal = canal.lower().lstrip("#")

    def _ler(self) -> None:
        import random
        import socket

        with socket.create_connection(self.SERVIDOR, timeout=30) as s:
            s.settimeout(1.0)
            apelido = f"justinfan{random.randint(10000, 99999)}"
            s.sendall(f"NICK {apelido}\r\nJOIN #{self.canal}\r\n".encode())
            self.ativo, self.erro = True, ""
            resto, silencio = "", time.time()
            while not self._parar.is_set():
                try:
                    dados = s.recv(65536)
                except socket.timeout:
                    if time.time() - silencio > 360:  # a Twitch manda PING a cada ~5 min
                        raise RuntimeError("o chat da Twitch parou de responder") from None
                    continue
                if not dados:
                    raise RuntimeError("a Twitch fechou a conexão do chat")
                silencio = time.time()
                resto += dados.decode("utf-8", errors="replace")
                *linhas, resto = resto.split("\r\n")
                novas = []
                for linha in linhas:
                    if linha.startswith("PING"):
                        s.sendall(linha.replace("PING", "PONG", 1).encode() + b"\r\n")
                    elif " PRIVMSG #" in linha:
                        texto = linha.split(" PRIVMSG #", 1)[1].split(" :", 1)
                        if len(texto) == 2:
                            novas.append((time.time(), texto[1]))
                if novas:
                    self._guardar(novas)


def para_live(url: str, video_id: str) -> ChatAoVivo:
    """O leitor de chat certo para a live (YouTube ou Twitch)."""
    if "twitch.tv" in (url or "").lower():
        import re as _re
        m = _re.search(r"twitch\.tv/([A-Za-z0-9_]{2,25})", url)
        return ChatTwitch(m.group(1) if m else video_id)
    return ChatAoVivo(video_id)
