"""Capas (thumbnails) geradas a partir do melhor quadro do corte.

Receita dos canais que mais recebem cliques: rosto ou ação em primeiro plano, cor e
contraste reforçados, fundo escurecido atrás do texto e de 1 a 3 palavras enormes em
duas cores. Vertical (1080×1920) para Shorts e Reels; horizontal (1280×720) para vídeos
longos.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from . import enquadramento, render, transcricao

log = logging.getLogger(__name__)
VISTA_DA_CAPA = {"facecam": ("reacao", 1.0), "rosto": ("rosto", 1.25), "dupla": ("dupla", 1.0),
                 "blur": ("preencher", 1.0)}


def _linhas(texto: str) -> list[str]:
    """Até 4 palavras, em uma ou duas linhas equilibradas."""
    termos = texto.replace("*", "").upper().split()[:4]
    if not termos:
        return []
    if len(termos) == 1 or len(" ".join(termos)) <= 9:
        return [" ".join(termos)]
    melhor = min(range(1, len(termos)),
                 key=lambda i: abs(len(" ".join(termos[:i])) - len(" ".join(termos[i:]))))
    return [" ".join(termos[:melhor]), " ".join(termos[melhor:])]


def gerar(video: str | Path, instante: float, saida: Path, texto: str, *, cena: dict | None,
          dimensoes: tuple[int, int], cores: dict, marca: str = "", horizontal: bool = False,
          selo: str = "") -> Path | None:
    """Gera a capa em JPEG. `selo` é um texto curto extra (ex.: "TOP 5"). None se falhar."""
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    w, h = dimensoes
    largura, altura = (1280, 720) if horizontal else (1080, 1920)
    if horizontal or not cena:
        quadro = (f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
                  f"crop={largura}:{altura},setsar=1[c]")
    else:
        vista, zoom = VISTA_DA_CAPA.get(cena["tipo"], ("preencher", 1.0))
        quadro = enquadramento.cadeia(vista, cena, w, h, zoom, "0:v", "c", "k", largura, altura,
                                      cores["acento"].replace("#", "0x"))
    linhas = _linhas(texto)
    maior = max((len(l) for l in linhas), default=1)
    # Corpo do texto: o maior que cabe em ~88% da largura (a Anton tem ~0,47 de largura por altura).
    corpo = int(min(altura * (0.26 if horizontal else 0.15), largura * 0.88 / (maior * 0.47)))
    base = altura * (0.60 if horizontal else 0.66)  # terço inferior, acima da interface
    eventos = []
    for k, linha in enumerate(linhas):
        cor = cores["destaque"] if k == 0 else "#FFFFFF"  # duas cores: lê-se de relance
        y = base + k * corpo * 1.08
        eventos.append(
            f"Dialogue: 1,0:00:00.00,0:00:10.00,Capa,,0,0,0,,{{\\an5\\pos({largura // 2},{y:.0f})"
            f"\\frz3\\fs{corpo}\\c{transcricao._cor_ass(cor)}}}{transcricao._limpar(linha)}")
    if selo:
        eventos.append(f"Dialogue: 2,0:00:00.00,0:00:10.00,Selo,,0,0,0,,{{\\an7\\pos(48,44)}}"
                       f"{transcricao._limpar(selo)}")
    if marca:
        eventos.append(f"Dialogue: 0,0:00:00.00,0:00:10.00,Marca,,0,0,0,,"
                       f"{{\\an9\\pos({largura - 40},48)}}{transcricao._limpar(marca)}")
    ass = saida.with_suffix(".ass")
    ass.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {largura}", f"PlayResY: {altura}",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Capa,Anton,{corpo},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,2,0,"
        f"1,{max(8, corpo // 14)},{max(4, corpo // 30)},5,0,0,0,1",
        f"Style: Selo,Anton,{int(altura * (0.11 if horizontal else 0.05))},&H00101010,&H00101010,"
        f"{transcricao._cor_ass(cores['destaque'])[:-1]},{transcricao._cor_ass(cores['destaque'])[:-1]},"
        "0,0,0,0,100,100,2,0,3,14,0,7,0,0,0,1",
        f"Style: Marca,Montserrat ExtraBold,{int(altura * (0.045 if horizontal else 0.02))},"
        "&H10FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,3,1,9,0,0,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *eventos]) + "\n", encoding="utf-8")
    # Cor e contraste reforçados, nitidez, e degradê escuro na metade de baixo para o texto.
    acabamento = ("format=yuv444p,eq=saturation=1.38:contrast=1.14:brightness=0.02,unsharp=5:5:0.9,"
                  "geq=lum='lum(X,Y)*(1-0.62*clip((Y-H*0.40)/(H*0.45),0,1))':cb='cb(X,Y)':cr='cr(X,Y)',"
                  f"vignette=PI/6,ass={ass.name}:fontsdir={render.pasta_fontes(saida.parent)}")
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, instante):.2f}", "-i",
             str(Path(video).resolve()), "-filter_complex", f"{quadro};[c]{acabamento}[v]",
             "-map", "[v]", "-frames:v", "1", "-q:v", "2", "-pix_fmt", "yuvj420p", saida.name],
            check=True, cwd=saida.parent, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:  # capa é um extra: nunca derruba o corte
        log.warning("Capa não gerada: %s", (e.stderr or "").strip()[-200:])
        return None
    finally:
        ass.unlink(missing_ok=True)
    return saida
