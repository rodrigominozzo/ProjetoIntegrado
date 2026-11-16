"""Renderização do corte final com ffmpeg: formato vertical, legendas e áudio nivelado."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import transcricao

TAMANHOS = {"vertical_blur": (1080, 1920), "vertical_crop": (1080, 1920), "original": (1920, 1080)}


def _filtro(formato: str, largura: int, altura: int) -> str:
    if formato == "vertical_blur":  # vídeo inteiro ao centro sobre fundo desfocado
        return (
            f"[0:v]split[a][b];"
            f"[a]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},boxblur=24:4,eq=brightness=-0.08[fundo];"
            f"[b]scale={largura}:-2[frente];[fundo][frente]overlay=(W-w)/2:(H-h)/2"
        )
    if formato == "vertical_crop":  # preenche a tela cortando as laterais
        return (f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
                f"crop={largura}:{altura}")
    return (f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
            f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2")


def renderizar(video: str | Path, inicio: float, fim: float, saida: Path, *, formato: str,
               palavras: list | None = None, credito: str = "") -> Path:
    """Gera o MP4 final (H.264/AAC, 30 fps) pronto para Shorts e Reels."""
    largura, altura = TAMANHOS.get(formato, TAMANHOS["vertical_blur"])
    duracao = fim - inicio
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)
    filtro = _filtro(formato, largura, altura)
    if palavras or credito:
        # Nome relativo + cwd evita o escape de caminhos dentro do filtro.
        ass = saida.with_suffix(".ass")
        ass.write_text(transcricao.gerar_ass(palavras or [], inicio, duracao, largura, altura,
                                             credito), encoding="utf-8")
        filtro += f",ass={ass.name}"
    filtro += ",fps=30,format=yuv420p[v]"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{inicio:.3f}", "-i", str(Path(video).resolve()),
         "-t", f"{duracao:.3f}", "-filter_complex", filtro,
         "-map", "[v]", "-map", "0:a:0?", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-movflags", "+faststart", str(saida)],
        check=True, cwd=saida.parent,
    )
    return saida
