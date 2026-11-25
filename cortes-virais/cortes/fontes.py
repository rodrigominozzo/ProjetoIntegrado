"""Fontes de vídeo: metadados, download e descoberta de lives/vídeos em alta."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path

import re

import requests

from . import seguranca

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"


# Vídeos com restrição de idade (e alguns bloqueios "confirme que não é um robô") exigem uma
# conta logada: o yt-dlp usa os cookies de um navegador ou de um arquivo cookies.txt.
COOKIES = {"navegador": "", "arquivo": ""}


def configurar(cfg: dict) -> None:
    f = cfg.get("fontes", {})
    COOKIES.update(navegador=(f.get("cookies_navegador") or "").strip().lower(),
                   arquivo=(f.get("cookies_arquivo") or "").strip())


def _opcoes_cookies() -> dict:
    if COOKIES["arquivo"] and Path(COOKIES["arquivo"]).is_file():
        return {"cookiefile": COOKIES["arquivo"]}
    if COOKIES["navegador"]:
        return {"cookiesfrombrowser": (COOKIES["navegador"],)}
    return {}


CONFIG_COOKIES = "Configurações → Vídeos com restrição"
ATUALIZAR = r'.venv\Scripts\pip install -U "yt-dlp[default]"'


def explicar_erro(e: Exception, avisos=()) -> Exception:
    """Troca os erros mais comuns do yt-dlp por uma explicação do que fazer. `avisos` são os
    avisos que o yt-dlp deu antes de falhar (é neles que aparece, por exemplo, a falha ao
    resolver o desafio JavaScript do YouTube, que depois vira um erro genérico)."""
    erro = str(e)
    tudo = "\n".join([erro, *avisos])
    if re.search(r"could not (copy|find|decrypt|open)[^\n]*cookie|cookies? database|"
                 r"failed to (decrypt|load)[^\n]*cookie|cookies?[^\n]*(locked|permission denied)|"
                 r"DPAPI|app.bound encryption|unsupported browser", tudo, re.I):
        return ValueError(
            "Não consegui ler os cookies do navegador escolhido: o Chrome e o Edge travam e "
            "criptografam os cookies no Windows, então o vídeo seria baixado sem a sua conta. "
            f"Use o Firefox (logado no YouTube) ou um arquivo cookies.txt, em {CONFIG_COOKIES}, "
            "e tente de novo.")
    if re.search(r"not a bot|confirm you.re not a robot", tudo, re.I):
        return ValueError(
            "O YouTube pediu para confirmar que não é um robô (não é restrição de idade). Em "
            f"{CONFIG_COOKIES}, escolha o navegador em que você está logado no YouTube (o "
            "Firefox funciona melhor) e tente de novo.")
    if re.search(r"confirm your age|age[- ]restricted|inappropriate for some users", erro, re.I):
        return ValueError(
            "Vídeo com restrição de idade: o YouTube só libera para uma conta logada e maior de "
            f"idade. Em {CONFIG_COOKIES}, escolha o navegador em que você está logado no YouTube "
            "(o Firefox funciona melhor) ou um arquivo cookies.txt, e tente de novo.")
    if re.search(r"Private video|vídeo privado|members.only|join this channel", tudo, re.I):
        return ValueError("Este vídeo é privado ou só para membros do canal: só quem tem acesso "
                          "consegue vê-lo.")
    if re.search(r"Video unavailable|video is unavailable|has been removed|no longer available|"
                 r"account associated with this video has been terminated|This video does not exist", tudo, re.I):
        return ValueError("Este vídeo foi removido ou não está disponível no YouTube.")
    if re.search(r"challenge solving failed|Signature solving failed|Error solving[^\n]*challenge|"
                 r"JavaScript runtime|\[jsc\]", tudo, re.I):
        return ValueError(
            "O YouTube mudou o player e esta versão do yt-dlp não conseguiu resolver o desafio "
            "JavaScript dele, então nenhum formato de vídeo foi liberado (não é restrição de "
            "idade). Atualize o yt-dlp: feche o programa, rode na pasta do Cortes Virais "
            f"{ATUALIZAR}, abra de novo e tente de novo.")
    if re.search(r"Requested format is not available|No video formats found", erro, re.I):
        return ValueError(
            "O YouTube não liberou nenhum formato de vídeo. Pode ser o vídeo ainda processando "
            f"(tente de novo em alguns minutos) ou o yt-dlp desatualizado ({ATUALIZAR}).")
    return e


class _Avisos:
    """Logger do yt-dlp que guarda os avisos (para explicar o erro depois) sem mostrá-los."""

    def __init__(self):
        self.avisos: list[str] = []

    def debug(self, msg):
        pass

    info = debug

    def warning(self, msg):
        self.avisos.append(str(msg))
        log.debug("yt-dlp: %s", msg)

    def error(self, msg):
        self.avisos.append(str(msg))


def _ydl(opcoes: dict):
    import yt_dlp

    registro = _Avisos()
    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": False, "logger": registro,
                            **_opcoes_cookies(), **opcoes})
    ydl.avisos = registro.avisos
    return ydl


def duracao_arquivo(caminho: str | Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(caminho)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(saida)["format"]["duration"])


def info(alvo: str) -> dict:
    """Metadados normalizados de uma URL do YouTube ou de um arquivo local."""
    if not re.match(r"https?://", alvo, re.I):
        p = Path(seguranca.validar_arquivo(alvo))
        return {"id": seguranca.nome_seguro(f"local-{p.stem}"), "titulo": p.stem, "canal": "", "canal_id": "",
                "url": "", "duracao": duracao_arquivo(p), "ao_vivo": False, "replay": [],
                "arquivo": str(p)}
    alvo = seguranca.validar_link(alvo)
    # ignore_no_formats_error: uma live agendada ainda não tem vídeo, mas os dados (com a
    # hora de início) vêm assim mesmo, em vez de um erro.
    ydl = _ydl({"skip_download": True, "ignore_no_formats_error": True})
    try:
        with ydl:
            d = ydl.extract_info(alvo, download=False)
    except Exception as e:  # noqa: BLE001
        raise explicar_erro(e, ydl.avisos) from None
    agendada = d.get("live_status") == "is_upcoming"
    # Só contam formatos de vídeo/áudio de verdade: com o acesso travado, o YouTube às vezes
    # manda só as miniaturas da barra de tempo ("storyboards"), e o download falhava depois
    # com um "Requested format is not available" que não explicava nada.
    reais = [f for f in d.get("formats") or []
             if (f.get("vcodec") or "none") != "none" or (f.get("acodec") or "none") != "none"]
    if not agendada and not reais and not d.get("url"):
        # Sem vídeo e sem ser agendada: descobre o motivo pelos avisos e pelos dados, em vez
        # de supor restrição de idade (em nov/2026 era o yt-dlp sem resolver o desafio JS).
        explicado = explicar_erro(RuntimeError("No video formats found"), ydl.avisos)
        if explicado.args[0].startswith("O YouTube não liberou") and (d.get("age_limit") or 0) >= 18:
            if _opcoes_cookies():
                raise ValueError(
                    "Vídeo com restrição de idade e os cookies escolhidos não liberaram: confira "
                    "se você está logado no YouTube nesse navegador, com uma conta maior de idade "
                    "(abra o vídeo lá para conferir), e tente de novo.")
            explicado = explicar_erro(RuntimeError("Sign in to confirm your age"))
        log.info("Sem formatos para %s; avisos do yt-dlp: %s", alvo, " | ".join(ydl.avisos)[:2000])
        raise explicado
    return {
        "id": seguranca.nome_seguro(str(d["id"])),
        "titulo": d.get("title") or "",
        "canal": d.get("channel") or d.get("uploader") or "",
        "canal_id": d.get("channel_id") or _canal_twitch(d, alvo),
        "url": d.get("webpage_url") or alvo,
        "duracao": float(d.get("duration") or 0),
        "ao_vivo": bool(d.get("is_live")),
        # Live que ainda vai começar: quando (timestamp) ou 0 se o YouTube não informou.
        "agendada": (float(d.get("release_timestamp") or 0) or 0.0) if agendada else None,
        # "Mais repetidos" do YouTube: [{start_time, end_time, value}]
        "replay": d.get("heatmap") or [],
    }


def baixar(url: str, pasta: Path, altura_max: int, idioma: str, progresso=None) -> dict:
    """Baixa vídeo, legendas (json3) e replay do chat. Devolve os caminhos encontrados."""
    url = seguranca.validar_link(url)
    pasta.mkdir(parents=True, exist_ok=True)
    modelo = str(pasta / "fonte.%(ext)s")
    with _ydl({
        "format": f"bv*[height<={altura_max}]+ba/b[height<={altura_max}]/b",
        "merge_output_format": "mp4",
        "outtmpl": modelo,
        "progress_hooks": [_gancho(progresso)] if progresso else [],
    }) as ydl:
        try:
            ydl.download([url])
        except Exception as e:  # noqa: BLE001
            explicado = explicar_erro(e, ydl.avisos)
            if explicado is e:
                raise
            raise explicado from None
    try:  # legendas e chat são opcionais: nem todo vídeo tem
        with _ydl({
            "skip_download": True, "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": [idioma, f"{idioma}-.*", "live_chat"],
            "subtitlesformat": "json3/best", "outtmpl": modelo,
        }) as ydl:
            ydl.download([url])
    except Exception as e:  # noqa: BLE001
        log.warning("Sem legendas/chat para %s: %s", url, e)
    video = next(pasta.glob("fonte.mp4"), None) or next(
        p for p in pasta.glob("fonte.*") if p.suffix in {".mkv", ".webm", ".mp4"})
    return {
        "video": video,
        "chat": next(pasta.glob("fonte.live_chat.json"), None),
        "legenda": next(iter(sorted(pasta.glob("fonte.*.json3"))), None),
    }


def baixar_trecho(url: str, pasta: Path, inicio: float, fim: float, altura_max: int) -> Path:
    """Baixa só um pedaço do vídeo (para refazer um corte depois que o original foi apagado).
    O corte é exato no início pedido: o tempo 0 do arquivo é `inicio` no vídeo original."""
    from yt_dlp.utils import download_range_func

    url = seguranca.validar_link(url)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"trecho_{int(inicio * 10)}_{int(fim * 10)}"
    with _ydl({
        "format": f"bv*[height<={altura_max}]+ba/b[height<={altura_max}]/b",
        "merge_output_format": "mp4", "outtmpl": str(pasta / f"{nome}.%(ext)s"),
        "download_ranges": download_range_func(None, [(inicio, fim)]),
        "force_keyframes_at_cuts": True,
    }) as ydl:
        ydl.download([url])
    return next(p for p in pasta.glob(f"{nome}.*") if p.suffix in {".mp4", ".mkv", ".webm"})


def _gancho(progresso):
    def gancho(d: dict) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if d.get("status") == "downloading" and total:
            progresso("Baixando o vídeo", d.get("downloaded_bytes", 0) / total)
    return gancho


def url_do_fluxo(url: str, altura: int) -> list[str]:
    """URLs HLS diretas de uma live em andamento: [vídeo+áudio] ou [vídeo, áudio].

    Desde nov/2026 o YouTube entrega muitas lives só com vídeo e áudio separados (nenhum
    formato completo), por isso aceita os dois separados e cai no completo se houver.
    """
    url = seguranca.validar_link(url)
    formato = (f"bv*[height<={altura}]+ba/b[height<={altura}]/bv*+ba/b")
    with _ydl({"skip_download": True, "format": formato}) as ydl:
        d = ydl.extract_info(url, download=False)
    partes = d.get("requested_formats") or [d]
    return [p["url"] for p in partes]


def entrada_ffmpeg_live(urls: list[str]) -> list[str]:
    """Argumentos de entrada do ffmpeg para gravar a live sem recodificar."""
    entrada = []
    # Vídeo e áudio separados podem começar em pedaços diferentes da transmissão (na live do
    # Cellbit, o áudio começava 5 s depois). O ffmpeg zera os dois relógios separadamente, e
    # essa defasagem é corrigida ao montar o corte (live.py lê os inícios no log da captura).
    for u in urls:
        entrada += ["-i", u]
    if len(urls) > 1:
        entrada += ["-map", "0:v:0", "-map", "1:a:0"]
    return entrada + ["-c", "copy"]


# --- descoberta -----------------------------------------------------------

def _canal_twitch(d: dict, alvo: str) -> str:
    """Canal da Twitch como "twitch:<login>" (o yt-dlp não dá um channel_id para a Twitch)."""
    if "twitch" not in (d.get("extractor") or "").lower() and "twitch.tv" not in alvo.lower():
        return ""
    login = d.get("uploader_id") or ""
    if not login:
        m = re.search(r"twitch\.tv/(?!videos/)([A-Za-z0-9_]{2,25})", alvo)
        login = m.group(1) if m else ""
    return f"twitch:{login.lower()}" if login else ""


def _do_canal_twitch(login: str) -> list[dict]:
    """A live do canal da Twitch, se ele estiver no ar agora (consulta pública da Twitch)."""
    import requests

    consulta = {"query": 'query{user(login:"%s"){displayName stream{id title viewersCount}}}' % login}
    r = requests.post("https://gql.twitch.tv/gql", json=consulta, timeout=20,
                      headers={"Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko"})
    usuario = (r.json().get("data") or {}).get("user") or {}
    stream = usuario.get("stream")
    if not stream:
        return []
    return [{"id": str(stream["id"]), "url": f"https://www.twitch.tv/{login}",
             "titulo": stream.get("title") or "", "canal": usuario.get("displayName") or login,
             "canal_id": f"twitch:{login}", "ao_vivo": True,
             "audiencia": stream.get("viewersCount") or 0}]


def _do_canal(canal_id: str, limite: int) -> list[dict]:
    """Lives e gravações recentes de um canal, sem gastar cota da API."""
    if canal_id.startswith("twitch:"):
        return _do_canal_twitch(canal_id.split(":", 1)[1])
    achados = []
    with _ydl({"extract_flat": True, "playlistend": limite, "ignoreerrors": True}) as ydl:
        d = ydl.extract_info(f"https://www.youtube.com/channel/{canal_id}/streams", download=False)
    for e in (d or {}).get("entries") or []:
        if not e or e.get("live_status") == "is_upcoming":
            continue
        achados.append({
            "id": e["id"], "url": f"https://www.youtube.com/watch?v={e['id']}",
            "titulo": e.get("title") or "", "canal": d.get("channel") or "", "canal_id": canal_id,
            "ao_vivo": e.get("live_status") == "is_live",
            "audiencia": e.get("concurrent_view_count") or e.get("view_count") or 0,
        })
    return achados


def _da_busca(cfg_busca: dict, ao_vivo: bool, chave: str) -> list[dict]:
    """Busca aberta por mais exibições (100 unidades de cota por consulta)."""
    ids: list[str] = []
    for consulta in cfg_busca["consultas"]:
        params = {
            "part": "id", "type": "video", "order": "viewCount", "q": consulta,
            "eventType": "live" if ao_vivo else "completed",
            "regionCode": cfg_busca["regiao"], "maxResults": cfg_busca["max_resultados"],
            "key": chave,
        }
        if not ao_vivo:
            desde = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=cfg_busca["dias"])
            params["publishedAfter"] = desde.strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(f"{API}/search", params=params, timeout=30)
        r.raise_for_status()
        ids += [i["id"]["videoId"] for i in r.json().get("items", [])]
    ids = list(dict.fromkeys(ids))[:50]
    if not ids:
        return []
    r = requests.get(f"{API}/videos", timeout=30, params={
        "part": "snippet,statistics,liveStreamingDetails", "id": ",".join(ids), "key": chave})
    r.raise_for_status()
    achados = []
    for v in r.json().get("items", []):
        aovivo = v["snippet"].get("liveBroadcastContent") == "live"
        audiencia = (v.get("liveStreamingDetails", {}).get("concurrentViewers") if aovivo
                     else v.get("statistics", {}).get("viewCount")) or 0
        achados.append({
            "id": v["id"], "url": f"https://www.youtube.com/watch?v={v['id']}",
            "titulo": v["snippet"]["title"], "canal": v["snippet"]["channelTitle"],
            "canal_id": v["snippet"]["channelId"], "ao_vivo": aovivo, "audiencia": int(audiencia),
        })
    return achados


def descobrir(cfg: dict) -> list[dict]:
    """Lives e gravações candidatas, das mais vistas para as menos vistas."""
    fontes = cfg["fontes"]
    canais = fontes["canais_autorizados"]
    achados: list[dict] = []
    if canais:
        for canal in canais:
            try:
                achados += _do_canal(canal, fontes["busca"]["max_resultados"])
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao listar canal %s: %s", canal, e)
    elif fontes["exigir_autorizacao"]:
        log.warning("Nenhum canal em fontes.canais_autorizados; nada a descobrir. "
                    "Adicione canais ou desligue fontes.exigir_autorizacao.")
    else:
        chave = os.environ.get("YOUTUBE_API_KEY")
        if not chave:
            raise RuntimeError("Defina YOUTUBE_API_KEY no .env para a busca aberta.")
        achados = _da_busca(fontes["busca"], True, chave) + _da_busca(fontes["busca"], False, chave)
    unicos = {a["id"]: a for a in achados}
    return sorted(unicos.values(), key=lambda a: a["audiencia"], reverse=True)
