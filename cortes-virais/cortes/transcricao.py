"""Transcrição com tempo por palavra: legendas do YouTube ou Whisper local (opcional)."""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)
Palavra = tuple[float, float, str]  # início, fim, texto
_whisper = None
_trava_whisper = threading.Lock()  # um modelo só, usado por várias análises e lives


def ler_json3(caminho: str | Path) -> list[Palavra]:
    """Legendas json3 do YouTube. As automáticas trazem tempo por palavra."""
    palavras: list[Palavra] = []
    eventos = json.loads(Path(caminho).read_text(encoding="utf-8")).get("events", [])
    for ev in eventos:
        segs = [s for s in ev.get("segs", []) if s.get("utf8", "").strip()]
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 2000) / 1000
        if any("tOffsetMs" in s for s in segs) or len(segs) > 1:
            inicios = [t0 + s.get("tOffsetMs", 0) / 1000 for s in segs]
            for i, s in enumerate(segs):
                fim = inicios[i + 1] if i + 1 < len(segs) else min(t0 + dur, inicios[i] + 1.0)
                palavras.append((inicios[i], max(fim, inicios[i] + 0.05), s["utf8"].strip()))
        else:  # linha inteira: distribui as palavras pela duração
            termos = segs[0]["utf8"].split()
            passo = dur / max(len(termos), 1)
            palavras += [(t0 + i * passo, t0 + (i + 1) * passo, w) for i, w in enumerate(termos)]
    palavras.sort(key=lambda p: p[0])
    # Legendas automáticas se sobrepõem entre eventos: remove repetições.
    limpas: list[Palavra] = []
    for p in palavras:
        if limpas and p[2] == limpas[-1][2] and p[0] - limpas[-1][0] < 0.3:
            continue
        limpas.append(p)
    return limpas


def whisper_disponivel() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcrever(video: str | Path, inicio: float, duracao: float, idioma: str,
                modelo: str) -> list[Palavra]:
    """Transcreve só o trecho pedido com faster-whisper. Lista vazia se não instalado."""
    global _whisper
    if not whisper_disponivel():
        return []
    from faster_whisper import WhisperModel

    with _trava_whisper, tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        if _whisper is None:
            _whisper = WhisperModel(modelo, device="auto", compute_type="int8")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{inicio:.2f}", "-t", f"{duracao:.2f}",
             "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", tmp.name], check=True)
        segmentos, _ = _whisper.transcribe(tmp.name, language=idioma, word_timestamps=True)
        return [(inicio + w.start, inicio + w.end, w.word.strip())
                for s in segmentos for w in (s.words or [])]


def recorte(palavras: list[Palavra], inicio: float, fim: float) -> list[Palavra]:
    return [p for p in palavras if p[0] >= inicio - 0.05 and p[0] < fim]


def texto(palavras: list[Palavra]) -> str:
    return " ".join(p[2] for p in palavras)


def ajustar_bordas(palavras: list[Palavra], inicio: float, fim: float,
                   folga: float = 2.5) -> tuple[float, float]:
    """Move início e fim para a pausa de fala mais próxima, para não cortar frases."""
    pausas = [palavras[i][0] - 0.1 for i in range(1, len(palavras))
              if palavras[i][0] - palavras[i - 1][1] >= 0.35]
    fins = [palavras[i - 1][1] + 0.15 for i in range(1, len(palavras))
            if palavras[i][0] - palavras[i - 1][1] >= 0.35]

    def perto(alvo: float, opcoes: list[float]) -> float:
        validas = [o for o in opcoes if abs(o - alvo) <= folga]
        return min(validas, key=lambda o: abs(o - alvo)) if validas else alvo

    return max(0.0, perto(inicio, pausas)), perto(fim, fins)


# --- legendas queimadas (ASS) ---------------------------------------------

def _tempo(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def gerar_ass(palavras: list[Palavra], inicio: float, duracao: float, largura: int, altura: int,
              credito: str = "") -> str:
    """Legendas em blocos curtos e grandes, no estilo de vídeos curtos."""
    vertical = altura > largura
    tamanho = 76 if vertical else 58
    margem = int(altura * 0.22) if vertical else int(altura * 0.08)
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {largura}", f"PlayResY: {altura}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Fala,DejaVu Sans,{tamanho},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,6,2,2,60,60,{margem},1",
        f"Style: Credito,DejaVu Sans,{int(tamanho * 0.42)},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,0,0,0,0,100,100,0,0,1,3,1,8,40,40,{int(altura * 0.06)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if credito:
        linhas.append(f"Dialogue: 0,{_tempo(0)},{_tempo(duracao)},Credito,,0,0,0,,{_limpar(credito)}")
    bloco: list[Palavra] = []
    blocos: list[list[Palavra]] = []
    for p in recorte(palavras, inicio, inicio + duracao):
        if bloco and (len(bloco) >= 3 or p[0] - bloco[0][0] > 1.4 or p[0] - bloco[-1][1] > 0.6):
            blocos.append(bloco)
            bloco = []
        bloco.append(p)
    if bloco:
        blocos.append(bloco)
    for i, b in enumerate(blocos):
        a = b[0][0] - inicio
        fim = min(b[-1][1] - inicio + 0.15, duracao)
        if i + 1 < len(blocos):
            fim = min(fim, blocos[i + 1][0][0] - inicio)
        if fim - a < 0.1:
            continue
        frase = _limpar(" ".join(p[2] for p in b)).upper()
        linhas.append(f"Dialogue: 1,{_tempo(a)},{_tempo(fim)},Fala,,0,0,0,,{frase}")
    return "\n".join(linhas) + "\n"


def _limpar(s: str) -> str:
    return s.replace("{", "(").replace("}", ")").replace("\n", " ").strip()
