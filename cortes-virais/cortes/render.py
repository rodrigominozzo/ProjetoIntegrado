"""Renderização do corte final com ffmpeg: edição dinâmica, legendas e áudio nivelado."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import edicao, enquadramento, sinais, transcricao

ENTRADA_NARRACAO = 0.15  # segundos até a voz começar

TAMANHOS = {"auto": (1080, 1920), "vertical_blur": (1080, 1920), "vertical_crop": (1080, 1920),
            "original": (1920, 1080)}

# Onde ficam as legendas e o gancho em cada layout (frações da altura).
POSICOES = {
    "blur":    {"fala": ("baixo", 0.22), "gancho": 0.15},   # faixas desfocadas acima/abaixo
    "rosto":   {"fala": ("baixo", 0.24), "gancho": 0.07},
    "dupla":   {"fala": ("meio", 0.0),   "gancho": 0.04},   # legenda na emenda dos painéis
    "facecam": {"fala": ("baixo", 0.28), "gancho": 0.03},  # serve à tela dividida e ao close
    "original": {"fala": ("baixo", 0.08), "gancho": 0.05},
}


def _tem_audio(video: str | Path) -> bool:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "json", str(video)], capture_output=True, text=True).stdout
    return bool(json.loads(saida or "{}").get("streams"))


def renderizar(video: str | Path, inicio: float, fim: float, saida: Path, *, formato: str,
               palavras: list | None = None, credito: str = "", gancho: str = "",
               marca: str = "", palavras_chave: list[str] | None = None,
               momento: float | None = None, abrir_com_pico: bool = False,
               narracao: dict | None = None,
               cfg_cortes: dict | None = None, cfg_edicao: dict | None = None) -> dict:
    """Gera o MP4 final (H.264/AAC, 30 fps). Devolve {"arquivo", "layout", "duracao", "planos"}.

    `narracao` = {"arquivo", "duracao", "texto", "volume", "fundo"}: voz de abertura,
    misturada por cima do áudio original abaixado.
    """
    cfg_cortes, cfg_edicao = cfg_cortes or {}, cfg_edicao or {}
    largura, altura = TAMANHOS.get(formato, TAMANHOS["auto"])
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    w, h = enquadramento.dimensoes(video)
    tem_audio = _tem_audio(video)

    # 1. Layout da cena.
    if formato == "auto" and w > h:
        layout = enquadramento.planejar(video, inicio, fim)
    elif formato == "vertical_crop":
        layout = {"tipo": "rosto", "rosto": {"cx": 0.5, "cy": 0.4, "w": 0.2, "h": 0.3}}
    else:
        layout = {"tipo": "blur"}

    # 2. Plano de edição (quais planos, em que ordem, o que sai).
    if formato == "original":
        plano = {"pedacos": [{"a": inicio, "b": fim, "vista": "original", "zoom": 1.0}],
                 "flash": None, "duracao": fim - inicio}
        video_fc = (f"[0:v]fps=30,trim=start=0:end={fim - inicio:.3f},setpts=PTS-STARTPTS,"
                    f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                    f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,setsar=1[vc]")
        if tem_audio:
            video_fc += f";[0:a:0]atrim=start=0:end={fim - inicio:.3f},asetpts=PTS-STARTPTS[ac]"
        tipo = "original"
    else:
        energia = sinais.volume_por_segundo(video, inicio, fim - inicio) if tem_audio else None
        plano = edicao.planejar(layout, inicio, fim, palavras=palavras, energia=energia,
                                momento=momento, abrir_com_pico=abrir_com_pico, cfg=cfg_edicao)
        video_fc = edicao.grafo(plano, layout, inicio, w, h, tem_audio, largura, altura)
        tipo = layout["tipo"]
    duracao = plano["duracao"]

    # 3. Acabamento: clarão na virada da abertura, barra de progresso, legendas.
    etapas = []
    if plano.get("flash"):
        t = plano["flash"]
        etapas.append(f"eq=brightness=0.35:enable='between(t,{t - 0.04:.2f},{t + 0.08:.2f})'")
    legendas = remapeadas = None
    if palavras and cfg_cortes.get("legendas", True) and tipo != "original":
        remapeadas = edicao.remapear(palavras, plano["pedacos"])
    elif palavras and cfg_cortes.get("legendas", True):
        remapeadas = [(a - inicio, b - inicio, t) for a, b, t in palavras if inicio <= a < fim]
    if remapeadas or credito or gancho or marca:
        legendas = saida.with_suffix(".ass")
        legendas.write_text(transcricao.gerar_ass(
            remapeadas or [], 0, duracao, largura, altura, credito=credito, gancho=gancho,
            marca=marca, posicao=POSICOES[tipo], karaoke=cfg_cortes.get("karaoke", True),
            cor_destaque=cfg_cortes.get("cor_destaque", "#FFE000"),
            palavras_chave=palavras_chave,
            narracao=(narracao["texto"], ENTRADA_NARRACAO, narracao["duracao"]) if narracao else None,
        ), encoding="utf-8")
        etapas.append(f"ass={legendas.name}")  # nome relativo + cwd evita escapes no filtro
    etapas.append("format=yuv420p")
    fc = video_fc
    if cfg_edicao.get("barra_progresso", True) and tipo != "original":
        cor = cfg_cortes.get("cor_destaque", "#FFE000").replace("#", "0x")
        fc += (f";color=c={cor}:s={largura}x10:r=30[barra];"
               f"[vc][barra]overlay=x='-w+w*t/{duracao:.3f}':y=H-h:shortest=1[vb]"
               f";[vb]{','.join(etapas)}[v]")
    else:
        fc += f";[vc]{','.join(etapas)}[v]"
    ultimo = max(p["b"] for p in plano["pedacos"])
    mapas = ["-map", "[v]"]
    entradas = ["-ss", f"{inicio:.3f}", "-t", f"{ultimo - inicio + 2:.3f}",
                "-i", str(Path(video).resolve())]
    if narracao:
        entradas += ["-i", str(Path(narracao["arquivo"]).resolve())]
        atraso = int(ENTRADA_NARRACAO * 1000)
        voz = (f"[1:a]aresample=48000,volume={narracao.get('volume', 1.0):.2f},"
               f"adelay={atraso}:all=1")
        if tem_audio:  # abaixa o original só enquanto a narração fala
            fim_n = ENTRADA_NARRACAO + narracao["duracao"]
            fc += (f";[ac]aresample=48000,volume='if(between(t,0,{fim_n + 0.1:.2f}),"
                   f"{narracao.get('fundo', 0.25):.2f},1)':eval=frame[fundo];{voz}[voz];"
                   f"[fundo][voz]amix=inputs=2:duration=first:normalize=0[ac2]")
            fc += ";[ac2]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        else:
            fc += f";{voz},apad[a]"
        mapas += ["-map", "[a]"]
    elif tem_audio:
        fc += ";[ac]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        mapas += ["-map", "[a]"]

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", fc, *mapas, "-t", f"{duracao:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-movflags", "+faststart", str(saida)],
        check=True, cwd=saida.parent,
    )
    return {"arquivo": saida, "layout": tipo, "duracao": duracao,
            "planos": [p["vista"] for p in plano["pedacos"]]}
