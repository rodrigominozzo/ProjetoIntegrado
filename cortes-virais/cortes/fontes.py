"""Fontes de vídeo: metadados, download e descoberta de lives/vídeos em alta."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"


def _ydl(opcoes: dict):
    import yt_dlp

    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, **opcoes})


def duracao_arquivo(caminho: str | Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(caminho)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(saida)["format"]["duration"])


def info(alvo: str) -> dict:
    """Metadados normalizados de uma URL do YouTube ou de um arquivo local."""
    if Path(alvo).exists():
        p = Path(alvo)
        return {"id": f"local-{p.stem}", "titulo": p.stem, "canal": "", "canal_id": "",
                "url": "", "duracao": duracao_arquivo(p), "ao_vivo": False, "replay": [],
                "arquivo": str(p)}
    with _ydl({"skip_download": True}) as ydl:
        d = ydl.extract_info(alvo, download=False)
    return {
        "id": d["id"],
        "titulo": d.get("title") or "",
        "canal": d.get("channel") or d.get("uploader") or "",
        "canal_id": d.get("channel_id") or "",
        "url": d.get("webpage_url") or alvo,
        "duracao": float(d.get("duration") or 0),
        "ao_vivo": bool(d.get("is_live")),
        # "Mais repetidos" do YouTube: [{start_time, end_time, value}]
        "replay": d.get("heatmap") or [],
    }


def baixar(url: str, pasta: Path, altura_max: int, idioma: str) -> dict:
    """Baixa vídeo, legendas (json3) e replay do chat. Devolve os caminhos encontrados."""
    pasta.mkdir(parents=True, exist_ok=True)
    modelo = str(pasta / "fonte.%(ext)s")
    with _ydl({
        "format": f"bv*[height<={altura_max}]+ba/b[height<={altura_max}]/b",
        "merge_output_format": "mp4",
        "outtmpl": modelo,
    }) as ydl:
        ydl.download([url])
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


def url_do_fluxo(url: str, altura: int) -> str:
    """URL HLS direta de uma live em andamento."""
    with _ydl({"skip_download": True, "format": f"b[height<={altura}]/b"}) as ydl:
        return ydl.extract_info(url, download=False)["url"]


# --- descoberta -----------------------------------------------------------

def _do_canal(canal_id: str, limite: int) -> list[dict]:
    """Lives e gravações recentes de um canal, sem gastar cota da API."""
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
