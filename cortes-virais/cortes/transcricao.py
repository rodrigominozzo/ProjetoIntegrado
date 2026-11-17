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


# Fontes embutidas (licença aberta OFL), no padrão dos canais de cortes: pesadas, sem
# serifa, legíveis em tela pequena. Valores: (escala do corpo, espaçamento entre letras).
FONTES = {
    "Montserrat Black": (1.0, 0), "Montserrat ExtraBold": (1.0, 0), "Poppins ExtraBold": (1.0, 0),
    "Anton": (1.22, 1), "Bangers": (1.2, 2),
}
PASTA_FONTES = Path(__file__).with_name("fontes_tipograficas")


def _cor_ass(hexa: str) -> str:
    """#RRGGBB -> &HBBGGRR& (formato de cor do ASS)."""
    h = hexa.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def gerar_ass(palavras: list[Palavra], inicio: float, duracao: float, largura: int, altura: int,
              credito: str = "", gancho: str = "", posicao: dict | None = None,
              karaoke: bool = True, cor_destaque: str = "#FFE000", marca: str = "",
              palavras_chave: list[str] | None = None, cor_chave: str = "#3CFF7A",
              narracoes: list[tuple[str, float, float]] | None = None,
              encerramento: tuple[str, float, float] | None = None,
              fonte: str = "Montserrat Black") -> str:
    """Legendas no estilo de vídeos curtos: blocos de até 3 palavras, com a palavra falada
    em destaque (karaokê), gancho fixo no topo e crédito discreto no rodapé."""
    vertical = altura > largura
    posicao = posicao or {"fala": ("baixo", 0.22 if vertical else 0.08), "gancho": 0.15}
    # Fontes condensadas pedem corpo maior para ocupar a mesma largura.
    escala, espaco = FONTES.get(fonte, (1.0, 0))
    tamanho = int((94 if vertical else 62) * escala)
    fonte_apoio = "Montserrat ExtraBold"
    onde, fracao = posicao["fala"]
    alinhamento = {"baixo": 2, "meio": 5, "topo": 8}[onde]
    margem = int(altura * fracao)
    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {largura}", f"PlayResY: {altura}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Fala,{fonte},{tamanho},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"0,0,0,0,100,100,{espaco},0,1,{int(tamanho * 0.09)},3,{alinhamento},60,60,{margem},1",
        # Gancho: texto escuro sobre caixa branca, como nos canais de cortes.
        f"Style: Gancho,{fonte},{int(tamanho * 0.62)},&H00101010,&H00101010,&H00FFFFFF,"
        f"&H00FFFFFF,0,0,0,0,100,100,0,0,3,14,0,8,70,70,{int(altura * posicao['gancho'])},1",
        f"Style: Credito,{fonte_apoio},{int(28 if vertical else 24)},&H40FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,0,0,0,0,100,100,0,0,1,3,1,1,40,40,{int(altura * 0.025)},1",
        f"Style: Marca,{fonte_apoio},{int(34 if vertical else 28)},&H30FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,3,1,3,40,40,{int(altura * 0.025)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if credito:
        linhas.append(f"Dialogue: 0,{_tempo(0)},{_tempo(duracao)},Credito,,0,0,0,,{_limpar(credito)}")
    if marca:
        linhas.append(f"Dialogue: 0,{_tempo(0)},{_tempo(duracao)},Marca,,0,0,0,,{_limpar(marca)}")
    if gancho:  # entra com um leve "pop" para chamar o olhar no primeiro instante
        linhas.append(f"Dialogue: 2,{_tempo(0)},{_tempo(duracao)},Gancho,,0,0,0,,"
                      f"{{\\fad(120,0)\\fscx85\\fscy85\\t(0,160,\\fscx100\\fscy100)}}{_limpar(gancho)}")
    chaves = {_normal(k) for k in (palavras_chave or [])}
    cor_k = _cor_ass(cor_chave)
    cobertas: list[tuple[float, float]] = []  # enquanto o narrador fala, a legenda é dele
    for texto_n, t0_n, dur_n in narracoes or []:
        termos_n = _limpar(texto_n).upper().split()
        grupos = [termos_n[i:i + 3] for i in range(0, len(termos_n), 3)]
        for i, g in enumerate(grupos):  # legenda da narração, em outra cor
            a, b = t0_n + dur_n * i / len(grupos), t0_n + dur_n * (i + 1) / len(grupos)
            linhas.append(f"Dialogue: 1,{_tempo(a)},{_tempo(b)},Fala,,0,0,0,,"
                          f"{{\\c&HFFE9A8&\\i1}}{' '.join(g)}")
        cobertas.append((t0_n - 0.3, t0_n + dur_n + 0.15))
    if encerramento:  # comentário final do canal, grande e centralizado sobre o quadro congelado
        texto_f, t0_f, dur_f = encerramento
        linhas.append(f"Dialogue: 3,{_tempo(t0_f)},{_tempo(t0_f + dur_f)},Fala,,80,80,0,,"
                      f"{{\\an5\\fad(150,0)\\c&HFFE9A8&}}{_limpar(texto_f)}")
        cobertas.append((t0_f - 0.1, t0_f + dur_f))
    bloco: list[Palavra] = []
    blocos: list[list[Palavra]] = []
    for p in recorte(palavras, inicio, inicio + duracao):
        if any(a <= p[0] - inicio < b for a, b in cobertas):
            continue
        if bloco and (len(bloco) >= 3 or p[0] - bloco[0][0] > 1.4 or p[0] - bloco[-1][1] > 0.6):
            blocos.append(bloco)
            bloco = []
        bloco.append(p)
    if bloco:
        blocos.append(bloco)
    cor = _cor_ass(cor_destaque)
    for i, b in enumerate(blocos):
        a = b[0][0] - inicio
        fim = min(b[-1][1] - inicio + 0.15, duracao)
        if i + 1 < len(blocos):
            fim = min(fim, blocos[i + 1][0][0] - inicio)
        if fim - a < 0.1:
            continue
        # Palavras-chave ficam sempre coloridas e um pouco maiores.
        termos = [(f"{{\\c{cor_k}\\fscx112\\fscy112}}{_limpar(p[2]).upper()}"
                   f"{{\\c&HFFFFFF&\\fscx100\\fscy100}}") if _normal(p[2]) in chaves
                  else _limpar(p[2]).upper() for p in b]
        if not karaoke:
            linhas.append(f"Dialogue: 1,{_tempo(a)},{_tempo(fim)},Fala,,0,0,0,,{' '.join(termos)}")
            continue
        for k, p in enumerate(b):  # um evento por palavra, com ela em destaque
            t0 = a if k == 0 else p[0] - inicio
            t1 = fim if k + 1 == len(b) else b[k + 1][0] - inicio
            if t1 - t0 < 0.03:
                continue
            frase = " ".join(f"{{\\c{cor}}}{t}{{\\c&HFFFFFF&}}" if j == k and "{" not in t else t
                             for j, t in enumerate(termos))
            if k == 0:  # cada bloco novo "salta" na tela
                frase = "{\\fscx90\\fscy90\\t(0,90,\\fscx100\\fscy100)}" + frase
            linhas.append(f"Dialogue: 1,{_tempo(t0)},{_tempo(t1)},Fala,,0,0,0,,{frase}")
    return "\n".join(linhas) + "\n"


def _normal(s: str) -> str:
    import unicodedata
    base = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in base if c.isalnum() and not unicodedata.combining(c))


def _limpar(s: str) -> str:
    return s.replace("{", "(").replace("}", ")").replace("\n", " ").strip()
