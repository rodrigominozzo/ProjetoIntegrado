"""Renderização do corte final com ffmpeg: edição dinâmica, legendas e áudio nivelado."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import edicao, enquadramento, sinais, transcricao

ENTRADA_NARRACAO = 0.15  # segundos até a voz começar

TAMANHOS = {"auto": (1080, 1920), "vertical_blur": (1080, 1920), "vertical_crop": (1080, 1920),
            "original": (1920, 1080)}

# Onde ficam as legendas e o gancho em cada layout (frações da altura).
POSICOES = {
    # Área segura de Shorts e Reels: nada importante nos ~28% de baixo nem nos ~8% de cima.
    "blur":    {"fala": ("baixo", 0.27), "gancho": 0.15},   # faixas desfocadas acima/abaixo
    "rosto":   {"fala": ("baixo", 0.30), "gancho": 0.085},
    "dupla":   {"fala": ("baixo", 0.30), "gancho": 0.085},  # serve à dupla e ao close
    "facecam": {"fala": ("baixo", 0.30), "gancho": 0.085},  # serve à tela dividida e ao close
    "original": {"fala": ("baixo", 0.08), "gancho": 0.10},
}


def pasta_fontes(destino: Path) -> str:
    """Copia as fontes embutidas para junto do corte e devolve o nome relativo da pasta."""
    copia = destino / "_fontes"
    if not copia.exists():
        shutil.copytree(transcricao.PASTA_FONTES, copia, ignore=shutil.ignore_patterns("*.txt"))
    return copia.name


def _tem_audio(video: str | Path) -> bool:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "json", str(video)], capture_output=True, text=True).stdout
    return bool(json.loads(saida or "{}").get("streams"))


def renderizar(video: str | Path, inicio: float, fim: float, saida: Path, *, formato: str,
               palavras: list | None = None, credito: str = "", gancho: str = "",
               marca: str = "", palavras_chave: list[str] | None = None,
               momento: float | None = None, abrir_com_pico: bool = False,
               narracoes: list[dict] | None = None, encerramento: dict | None = None,
               cfg_cortes: dict | None = None, cfg_edicao: dict | None = None) -> dict:
    """Gera o MP4 final (H.264/AAC, 30 fps). Devolve {"arquivo", "layout", "duracao", "planos"}.

    `narracoes` = [{"arquivo", "duracao", "texto", "t", "volume", "fundo"}]: falas do
    narrador, misturadas por cima do áudio original abaixado. `t` é o instante no vídeo
    de origem (None = abertura). `encerramento` = {"texto", "duracao", "arquivo"?}:
    comentário final sobre o último quadro congelado.
    """
    cfg_cortes, cfg_edicao = cfg_cortes or {}, cfg_edicao or {}
    largura, altura = TAMANHOS.get(formato, TAMANHOS["auto"])
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    w, h = enquadramento.dimensoes(video)
    tem_audio = _tem_audio(video)
    cores = transcricao.tema(cfg_cortes)

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
        falantes = None
        if layout["tipo"] == "dupla" and cfg_edicao.get("seguir_falante", True) \
                and cfg_edicao.get("dinamica", True):
            try:
                falantes = enquadramento.quem_fala(video, inicio, fim, layout["pessoas"])
            except Exception:  # noqa: BLE001 — na dúvida, fica a dupla o tempo todo
                falantes = None
        plano = edicao.planejar(layout, inicio, fim, palavras=palavras, energia=energia,
                                momento=momento, abrir_com_pico=abrir_com_pico, cfg=cfg_edicao,
                                falantes=falantes)
        video_fc = edicao.grafo(plano, layout, inicio, w, h, tem_audio, largura, altura,
                                acento=cores["acento"].replace("#", "0x"))
        tipo = layout["tipo"]
    duracao = plano["duracao"]

    # 3. Narrações: cada uma entra no seu instante; as que não cabem ou se atropelam saem.
    vozes, livre = [], 0.0
    for n in narracoes or []:
        t = ENTRADA_NARRACAO if n.get("t") is None else (
            edicao.tempo_de_saida(plano, n["t"]) if tipo != "original" else n["t"] - inicio)
        if t is None or t < livre or t + n["duracao"] > duracao - 0.3:
            continue
        vozes.append({**n, "saida": t})
        livre = t + n["duracao"] + 0.6
    corpo = duracao  # duração do vídeo antes do encerramento
    if encerramento:  # quadro final congelado, com o comentário de fechamento do canal
        vozes.append({**encerramento, "saida": corpo + 0.25, "final": True})
        duracao = corpo + encerramento["duracao"] + 0.7

    # 4. Acabamento: clarão na virada da abertura, encerramento, barra de progresso, legendas.
    antes, depois = [], []  # filtros antes e depois da barra de progresso
    if cfg_edicao.get("realce", True) and tipo != "original":
        # Acabamento de cor: um pouco mais de saturação e contraste, nitidez (os recortes
        # ampliados ficam moles) e vinheta leve para puxar o olhar ao centro.
        antes.append("eq=saturation=1.12:contrast=1.04,unsharp=5:5:0.6:5:5:0,vignette=PI/7")
    if plano.get("flash"):
        t = plano["flash"]
        antes.append(f"eq=brightness=0.35:enable='between(t,{t - 0.04:.2f},{t + 0.08:.2f})'")
    if encerramento:
        antes.append(f"tpad=stop_mode=clone:stop_duration={duracao - corpo:.2f},"
                      f"boxblur=12:2:enable='gte(t,{corpo:.2f})',"
                      f"eq=brightness=-0.22:enable='gte(t,{corpo:.2f})'")
    remapeadas = None
    if palavras and cfg_cortes.get("legendas", True) and tipo != "original":
        remapeadas = edicao.remapear(palavras, plano["pedacos"])
    elif palavras and cfg_cortes.get("legendas", True):
        remapeadas = [(a - inicio, b - inicio, t) for a, b, t in palavras if inicio <= a < fim]
    if remapeadas or credito or gancho or marca or vozes:
        legendas = saida.with_suffix(".ass")
        legendas.write_text(transcricao.gerar_ass(
            remapeadas or [], 0, duracao, largura, altura, credito=credito, gancho=gancho,
            marca=marca, posicao=POSICOES[tipo], karaoke=cfg_cortes.get("karaoke", True),
            cores=cores, palavras_chave=palavras_chave, fonte=cfg_cortes.get("fonte", "Montserrat Black"),
            narracoes=[(v["texto"], v["saida"], v["duracao"]) for v in vozes if not v.get("final")],
            encerramento=next(((v["texto"], v["saida"], v["duracao"] + 0.4) for v in vozes
                               if v.get("final")), None),
        ), encoding="utf-8")
        depois.append(f"ass={legendas.name}:fontsdir={pasta_fontes(saida.parent)}")  # nomes relativos + cwd evitam escapes no filtro
    depois.append("format=yuv420p")
    fc = video_fc + f";[vc]{','.join(antes) or 'null'}[vp]"
    if cfg_edicao.get("barra_progresso", True) and tipo != "original":
        cor = cores["acento"].replace("#", "0x")  # no topo: o rodapé é coberto pelos aplicativos
        fc += (f";color=c={cor}:s={largura}x8:r=30[barra];"
               f"[vp][barra]overlay=x='-w+w*t/{duracao:.3f}':y=0:shortest=1[vb]"
               f";[vb]{','.join(depois)}[v]")
    else:
        fc += f";[vp]{','.join(depois)}[v]"
    ultimo = max(p["b"] for p in plano["pedacos"])
    mapas = ["-map", "[v]", "-map", "[a]"]
    entradas = ["-ss", f"{inicio:.3f}", "-t", f"{ultimo - inicio + 2:.3f}",
                "-i", str(Path(video).resolve())]
    falados = [v for v in vozes if v.get("arquivo")]
    for v in falados:
        entradas += ["-i", str(Path(v["arquivo"]).resolve())]
    volume, fundo = (falados[0].get("volume", 1.0), falados[0].get("fundo", 0.25)) if falados else (1, 1)
    if tem_audio:
        fc += f";[ac]aresample=48000,apad=whole_dur={duracao:.3f}"
        if falados:  # abaixa o original só enquanto o narrador fala
            janelas = "+".join(f"between(t,{v['saida'] - 0.1:.2f},{v['saida'] + v['duracao'] + 0.1:.2f})"
                               for v in falados)
            fc += f",volume='if({janelas},{fundo:.2f},1)':eval=frame"
        fc += "[fundo]"
    else:
        fc += f";anullsrc=r=48000:cl=stereo,atrim=duration={duracao:.3f}[fundo]"
    for k, v in enumerate(falados):
        fc += (f";[{k + 1}:a]aresample=48000,volume={volume:.2f},"
               f"adelay={int(v['saida'] * 1000)}:all=1[n{k}]")
    if falados:
        fc += (";[fundo]" + "".join(f"[n{k}]" for k in range(len(falados)))
               + f"amix=inputs={len(falados) + 1}:duration=first:normalize=0[mix]")
    fc += f";[{'mix' if falados else 'fundo'}]loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", fc, *mapas, "-t", f"{duracao:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(saida)],
        check=True, cwd=saida.parent,
    )
    m_saida = None
    if plano.get("momento") is not None and tipo != "original":
        m_saida = edicao.tempo_de_saida(plano, plano["momento"])
    return {"arquivo": saida, "layout": tipo, "duracao": duracao, "cena": layout,
            "dimensoes": (w, h), "momento": plano.get("momento"), "momento_saida": m_saida,
            "planos": [p["vista"] for p in plano["pedacos"]]}
