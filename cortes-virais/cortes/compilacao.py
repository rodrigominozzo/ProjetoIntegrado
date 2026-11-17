"""Compilação narrada: um vídeo horizontal "Top N momentos" com contagem regressiva.

É o formato que a política do YouTube cita como aceito para material de terceiros —
trechos editados com um fio condutor e comentário próprio — e, por ser vídeo longo,
soma horas de exibição e rende mais por visualização do que Shorts. Sai só no YouTube.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from . import fontes, narracao, render
from .banco import Banco

log = logging.getLogger(__name__)
EXTENSO = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez"]
CODIFICACAO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


def _limpo(texto: str) -> str:
    return texto.replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _cartao(video: Path, instante: float, saida: Path, grande: str, pequeno: str,
            fala: str, cfg: dict) -> float:
    """Tela de passagem: quadro do vídeo desfocado, número grande, frase e voz. Devolve a duração."""
    quadro = saida.with_suffix(".jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{instante:.2f}", "-i", str(video),
                    "-frames:v", "1", "-q:v", "3", str(quadro)], check=True)
    voz = saida.with_suffix(".voz.wav")
    dur_voz = narracao.sintetizar(fala, voz, cfg)
    duracao = max(2.4, (dur_voz or 0) + 0.7)
    ass = saida.with_suffix(".ass")
    ass.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Grande,Montserrat Black,230,&H0000E0FF,&H0000E0FF,&H00000000,&H80000000,0,0,0,0,100,100,"
        "0,0,1,8,3,5,80,80,0,1",
        "Style: Pequeno,Montserrat ExtraBold,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,"
        "0,0,1,5,2,5,160,160,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:59.00,Grande,,0,0,0,,{{\\pos(960,400)\\fad(150,0)}}{_limpo(grande)}",
        f"Dialogue: 0,0:00:00.00,0:00:59.00,Pequeno,,0,0,0,,{{\\pos(960,680)\\fad(300,0)}}{_limpo(pequeno)}",
    ]) + "\n", encoding="utf-8")
    som = ["-i", str(voz)] if dur_voz else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "30", "-i", quadro.name, *som,
         "-filter_complex",
         f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=22:3,"
         f"eq=brightness=-0.28,ass={ass.name}:fontsdir={render.pasta_fontes(saida.parent)},setsar=1[v];[1:a]aresample=48000,apad[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{duracao:.2f}", *CODIFICACAO, saida.name],
        check=True, cwd=saida.parent)
    return duracao


def _marca(segundos: float) -> str:
    return f"{int(segundos // 60)}:{int(segundos % 60):02d}"


def montar(video: Path, escolhidos: list[dict], meta: dict, cfg: dict, banco: Banco,
           pasta: Path) -> int | None:
    """Monta a compilação a partir dos cortes escolhidos de um vídeo. Devolve o ID, ou None."""
    n = len(escolhidos)
    if not cfg["compilacao"]["ativa"] or n < cfg["compilacao"]["minimo"]:
        return None
    trabalho = pasta / "compilacao"
    trabalho.mkdir(parents=True, exist_ok=True)
    ordem = sorted(escolhidos, key=lambda c: c["nota"])  # do pior para o melhor
    canal = meta.get("canal") or "do vídeo"
    partes, capitulos, t = [], [], 0.0

    abertura = trabalho / "p00.mp4"
    t += _cartao(video, ordem[-1].get("inicio_arquivo", ordem[-1]["inicio"]), abertura,
                 f"TOP {n}", meta["titulo"][:70],
                 f"Os {EXTENSO[n] if n <= 10 else n} melhores momentos de {canal}. "
                 "O primeiro lugar fica para o final.", cfg)
    partes.append(abertura)
    capitulos.append((0.0, "Abertura"))
    sem_barra = {**cfg["edicao"], "barra_progresso": False}
    for k, c in enumerate(ordem):
        posicao = n - k
        ini = c.get("inicio_arquivo", c["inicio"])
        fim = c.get("fim_arquivo", c["fim"])
        frase = c.get("gancho") or c["titulo"]
        cartao = trabalho / f"p{k + 1:02d}a.mp4"
        capitulos.append((t, f"{posicao}º — {c['titulo']}"))
        t += _cartao(video, ini, cartao, f"#{posicao}", frase,
                     f"Número {EXTENSO[posicao] if posicao <= 10 else posicao}. {frase}", cfg)
        trecho = trabalho / f"p{k + 1:02d}b.mp4"
        falas, _ = narracao.preparar(c, trecho, ini, cfg)
        feito = render.renderizar(
            video, ini, fim, trecho, formato="original", palavras=c.get("falas"),
            marca=cfg["cortes"]["marca"], palavras_chave=c.get("palavras_chave"),
            narracoes=falas, cfg_cortes=cfg["cortes"], cfg_edicao=sem_barra)
        t += feito["duracao"]
        partes += [cartao, trecho]

    lista = trabalho / "lista.txt"
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes))
    saida = pasta / "compilacao.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista.name,
                    "-c", "copy", "-movflags", "+faststart", str(saida.resolve())],
                   check=True, cwd=trabalho)
    shutil.rmtree(trabalho, ignore_errors=True)

    descricao = (f"Os {n} melhores momentos de: {meta['titulo']}\n\n"
                 + "\n".join(f"{_marca(tc)} {nome}" for tc, nome in capitulos))
    if cfg["publicar"]["creditar_fonte"] and meta.get("url"):
        descricao += f"\n\nFonte: {canal} — {meta['url']}"
    marcas = list(dict.fromkeys(h for c in ordem for h in c["hashtags"]))[:8]
    corte_id = banco.novo_corte(
        video_id=meta["id"], origem="compilacao", inicio=0, fim=fontes.duracao_arquivo(saida),
        nota=max(c["nota"] for c in ordem), titulo=f"Top {n} momentos — {meta['titulo']}"[:95],
        descricao=descricao, hashtags=marcas, arquivo=saida, teste=bool(meta.get("teste")),
        layout="compilacao", narracao="Contagem regressiva narrada")
    log.info("Compilação %s pronta: %d momentos, %s.", corte_id, n, _marca(t))
    return corte_id
