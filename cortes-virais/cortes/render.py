"""Renderização do corte final com ffmpeg: enquadramento vertical, legendas e áudio nivelado."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import enquadramento, transcricao

TAMANHOS = {"auto": (1080, 1920), "vertical_blur": (1080, 1920), "vertical_crop": (1080, 1920),
            "original": (1920, 1080)}

# Onde ficam as legendas e o gancho em cada layout (frações da altura).
POSICOES = {
    "blur":    {"fala": ("baixo", 0.22), "gancho": 0.15},   # faixas desfocadas acima/abaixo
    "rosto":   {"fala": ("baixo", 0.24), "gancho": 0.07},
    "dupla":   {"fala": ("meio", 0.0),   "gancho": 0.04},   # legenda na emenda dos painéis
    "facecam": {"fala": ("topo", 0.31),  "gancho": 0.03},   # logo abaixo da câmera
    "original": {"fala": ("baixo", 0.08), "gancho": 0.05},
}


def _filtro_fixo(formato: str, largura: int, altura: int) -> str:
    if formato == "vertical_crop":  # preenche a tela cortando as laterais
        return (f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
                f"crop={largura}:{altura}")
    if formato == "original":
        return (f"[0:v]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2")
    return (  # vídeo inteiro ao centro sobre fundo desfocado
        f"[0:v]split[a][b];"
        f"[a]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
        f"crop={largura}:{altura},boxblur=24:4,eq=brightness=-0.08[fundo];"
        f"[b]scale={largura}:-2[frente];[fundo][frente]overlay=(W-w)/2:(H-h)/2"
    )


def renderizar(video: str | Path, inicio: float, fim: float, saida: Path, *, formato: str,
               palavras: list | None = None, credito: str = "", gancho: str = "",
               karaoke: bool = True, cor_destaque: str = "#FFE000") -> tuple[Path, str]:
    """Gera o MP4 final (H.264/AAC, 30 fps). Devolve o arquivo e o layout usado."""
    largura, altura = TAMANHOS.get(formato, TAMANHOS["auto"])
    duracao = fim - inicio
    saida = Path(saida).resolve()
    saida.parent.mkdir(parents=True, exist_ok=True)

    tipo, filtro = "blur", None
    if formato == "auto":
        w, h = enquadramento.dimensoes(video)
        if w > h:  # vídeo já vertical não precisa de reenquadramento
            layout = enquadramento.planejar(video, inicio, fim)
            filtro = enquadramento.filtro(layout, w, h, largura, altura)
            tipo = layout["tipo"] if filtro else "blur"
    elif formato == "original":
        tipo = "original"
    elif formato == "vertical_crop":
        tipo = "rosto"
    filtro = filtro or _filtro_fixo(formato, largura, altura)

    if palavras or credito or gancho:
        # Nome relativo + cwd evita o escape de caminhos dentro do filtro.
        ass = saida.with_suffix(".ass")
        ass.write_text(transcricao.gerar_ass(
            palavras or [], inicio, duracao, largura, altura, credito=credito, gancho=gancho,
            posicao=POSICOES[tipo], karaoke=karaoke, cor_destaque=cor_destaque), encoding="utf-8")
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
    return saida, tipo
