"""Enquadramento vertical inteligente: decide o layout do corte a partir dos rostos na cena.

  rosto    — uma pessoa falando: recorte 9:16 centrado nela
  dupla    — duas pessoas (podcast, entrevista): uma em cima, outra embaixo
  facecam  — rosto pequeno num canto (gameplay): câmera em cima, jogo embaixo
  blur     — sem rosto consistente: vídeo inteiro sobre fundo desfocado

Usa OpenCV se estiver instalado; sem ele, tudo sai no layout blur.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
_detector = None


def disponivel() -> bool:
    try:
        import cv2
        return hasattr(cv2, "CascadeClassifier")
    except ImportError:
        return False


def dimensoes(video: str | Path) -> tuple[int, int]:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout
    fluxo = json.loads(saida)["streams"][0]
    return int(fluxo["width"]), int(fluxo["height"])


def rostos_por_quadro(video: str | Path, inicio: float, fim: float,
                      amostras: int = 14) -> list[list[tuple[float, float, float, float]]]:
    """Rostos (cx, cy, largura, altura — frações do quadro) em quadros espaçados do trecho."""
    import cv2

    global _detector
    if _detector is None:
        _detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    w, h = dimensoes(video)
    lw = min(1280, w // 2 * 2)
    lh = int(h * lw / w) // 2 * 2
    quadros = []
    for i in range(amostras):
        t = inicio + (fim - inicio) * (i + 0.5) / amostras
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", f"scale={lw}:{lh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True)
        if len(r.stdout) != lw * lh:
            continue
        cinza = np.frombuffer(r.stdout, dtype=np.uint8).reshape(lh, lw)
        achados = _detector.detectMultiScale(cinza, 1.1, 6, minSize=(32, 32))
        quadros.append([((x + fw / 2) / lw, (y + fh / 2) / lh, fw / lw, fh / lh)
                        for x, y, fw, fh in achados])
    return quadros


def classificar(quadros: list[list[tuple[float, float, float, float]]]) -> dict:
    """Escolhe o layout a partir das detecções. Separado da detecção para ser testável."""
    n = len(quadros)
    if not n:
        return {"tipo": "blur"}
    # Agrupa as detecções pela posição horizontal: cada grupo é uma pessoa.
    grupos: list[dict] = []
    for i, rostos in enumerate(quadros):
        for cx, cy, fw, fh in rostos:
            g = next((g for g in grupos if abs(g["cx"] - cx) < 0.14 and abs(g["cy"] - cy) < 0.25),
                     None)
            if g is None:
                g = {"cx": cx, "cy": cy, "itens": [], "quadros": set()}
                grupos.append(g)
            g["itens"].append((cx, cy, fw, fh))
            g["quadros"].add(i)
            g["cx"] = float(np.median([it[0] for it in g["itens"]]))
            g["cy"] = float(np.median([it[1] for it in g["itens"]]))
    pessoas = []
    for g in grupos:
        presenca = len(g["quadros"]) / n
        if presenca >= 0.4:  # descarta detecções esporádicas (falsos positivos)
            pessoas.append({"cx": g["cx"], "cy": g["cy"], "presenca": presenca,
                            "w": float(np.median([it[2] for it in g["itens"]])),
                            "h": float(np.median([it[3] for it in g["itens"]]))})
    pessoas.sort(key=lambda p: p["presenca"] * p["w"], reverse=True)
    if not pessoas:
        return {"tipo": "blur"}
    a = pessoas[0]
    if len(pessoas) >= 2 and pessoas[1]["w"] >= 0.05 and pessoas[1]["w"] >= a["w"] * 0.45:
        dupla = sorted(pessoas[:2], key=lambda p: p["cx"])
        return {"tipo": "dupla", "pessoas": dupla}
    # Facecam: rosto pequeno encostado num canto do quadro (o resto é jogo ou tela).
    no_canto = (a["cx"] < 0.25 or a["cx"] > 0.75) and (a["cy"] < 0.3 or a["cy"] > 0.6)
    if a["w"] < 0.10 and no_canto:
        return {"tipo": "facecam", "rosto": a}
    return {"tipo": "rosto", "rosto": a}


def quem_fala(video: str | Path, inicio: float, fim: float, pessoas: list[dict],
              fps: int = 6) -> list[tuple[float, float, int]]:
    """Em cenas com duas pessoas, estima quem está falando pelo movimento da boca.

    Devolve trechos (início, fim, índice da pessoa) em que uma delas claramente fala
    sozinha por pelo menos 1,5 s. Onde as duas falam, ou nenhuma, não devolve nada.
    """
    w, h = dimensoes(video)
    lw = 640
    lh = int(h * lw / w) // 2 * 2
    bruto = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{inicio:.2f}", "-t", f"{fim - inicio:.2f}", "-i",
         str(video), "-vf", f"fps={fps},scale={lw}:{lh}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True).stdout
    n = len(bruto) // (lw * lh)
    if n < fps * 3 or len(pessoas) < 2:
        return []
    quadros = np.frombuffer(bruto[: n * lw * lh], dtype=np.uint8).reshape(n, lh, lw)
    movimento = []
    for p in pessoas[:2]:  # região da boca: metade de baixo do rosto
        x0, x1 = int((p["cx"] - p["w"] * 0.35) * lw), int((p["cx"] + p["w"] * 0.35) * lw)
        y0, y1 = int((p["cy"] + p["h"] * 0.05) * lh), int((p["cy"] + p["h"] * 0.5) * lh)
        boca = quadros[:, max(0, y0):max(1, y1), max(0, x0):max(1, x1)].astype(np.int16)
        if boca.size == 0:
            return []
        mov = np.abs(np.diff(boca, axis=0)).mean(axis=(1, 2))
        movimento.append(np.convolve(mov, np.ones(fps) / fps, mode="same"))  # média de 1 s
    a, b = movimento
    piso = 0.5  # abaixo disso é ruído de compressão, não fala
    rotulos = np.where((a > b * 1.4) & (a > piso), 0, np.where((b > a * 1.4) & (b > piso), 1, -1))
    trechos, comeco = [], 0
    for i in range(1, len(rotulos) + 1):
        if i == len(rotulos) or rotulos[i] != rotulos[comeco]:
            if rotulos[comeco] >= 0 and (i - comeco) / fps >= 1.5:
                trechos.append((inicio + comeco / fps, inicio + i / fps, int(rotulos[comeco])))
            comeco = i
    return trechos


def planejar(video: str | Path, inicio: float, fim: float) -> dict:
    if not disponivel():
        return {"tipo": "blur"}
    try:
        return classificar(rostos_por_quadro(video, inicio, fim))
    except Exception as e:  # noqa: BLE001 — enquadramento nunca deve derrubar o corte
        log.warning("Detecção de rostos falhou (%s); usando fundo desfocado.", e)
        return {"tipo": "blur"}


def _par(v: float) -> int:
    return max(2, int(v) // 2 * 2)


def _caixa(cx: float, cy: float, cw: float, ch: float, w: int, h: int) -> str:
    """Filtro crop com a caixa centrada em (cx, cy), mantida dentro do quadro."""
    cw, ch = _par(min(cw, w)), _par(min(ch, h))
    x = int(min(max(cx - cw / 2, 0), w - cw))
    y = int(min(max(cy - ch / 2, 0), h - ch))
    return f"crop={cw}:{ch}:{x}:{y}"


VISTA_BASE = {"rosto": "rosto", "dupla": "dupla", "facecam": "dividido", "blur": "blur"}


def cadeia(vista: str, layout: dict, w: int, h: int, zoom: float, ent: str, sai: str, p: str,
           largura: int = 1080, altura: int = 1920, acento: str = "0xFFE000") -> str:
    """Filtros que levam o fluxo [ent] ao quadro vertical [sai] na vista pedida.

    Vistas: rosto (9:16 no rosto), reacao (close no rosto da facecam), jogo/preencher
    (recorte central), dividido (câmera em cima, jogo embaixo), dupla, blur.
    `p` é um prefixo único para os rótulos internos.
    """
    fim = f"scale={largura}:{altura},setsar=1[{sai}]"
    proporcao = largura / altura
    r = layout.get("rosto")
    if vista == "rosto" and r:
        ch = h / zoom
        cy = h / 2 if zoom <= 1.01 else r["cy"] * h + ch * 0.12
        return f"[{ent}]{_caixa(r['cx'] * w, cy, ch * proporcao, ch, w, h)},{fim}"
    if vista.startswith("pessoa") and layout.get("pessoas"):  # close em quem está falando
        pessoa = layout["pessoas"][int(vista[-1])]
        return f"[{ent}]{_caixa(pessoa['cx'] * w, h / 2, h * proporcao, h, w, h)},{fim}"
    if vista == "reacao" and r:
        ch = min(h, r["h"] * h * 4.2 / zoom)
        return f"[{ent}]{_caixa(r['cx'] * w, r['cy'] * h + ch * 0.1, ch * proporcao, ch, w, h)},{fim}"
    if vista in {"jogo", "preencher"}:
        ch = h / zoom
        return f"[{ent}]{_caixa(w / 2, h / 2, ch * proporcao, ch, w, h)},{fim}"
    if vista == "dupla" and layout.get("pessoas"):
        meia = altura // 2
        cw = min(h * largura / meia, w * 0.5)
        ch = cw * meia / largura
        a, b = layout["pessoas"][:2]
        return (f"[{ent}]split[{p}a][{p}b];"
                f"[{p}a]{_caixa(a['cx'] * w, a['cy'] * h + ch * 0.12, cw, ch, w, h)},"
                f"scale={largura}:{meia},setsar=1[{p}t];"
                f"[{p}b]{_caixa(b['cx'] * w, b['cy'] * h + ch * 0.12, cw, ch, w, h)},"
                f"scale={largura}:{meia},setsar=1[{p}u];[{p}t][{p}u]vstack,"
                f"drawbox=x=0:y={meia - 4}:w=iw:h=8:color={acento}:t=fill[{sai}]")
    if vista == "dividido" and r:
        topo = altura // 3
        cw = min(r["w"] * w * 3.4, w)
        ch = cw * topo / largura
        # rosto na parte de baixo do painel: o topo fica livre para o gancho
        cam = _caixa(r["cx"] * w, r["cy"] * h - ch * 0.12, cw, ch, w, h)
        jogo = _caixa(w / 2, h / 2, h * largura / (altura - topo), h, w, h)
        return (f"[{ent}]split[{p}a][{p}b];[{p}a]{cam},scale={largura}:{topo},setsar=1[{p}t];"
                f"[{p}b]{jogo},scale={largura}:{altura - topo},setsar=1[{p}u];"
                f"[{p}t][{p}u]vstack,drawbox=x=0:y={topo - 4}:w=iw:h=8:color={acento}:t=fill[{sai}]")
    # blur: vídeo inteiro ao centro sobre fundo desfocado
    return (f"[{ent}]split[{p}a][{p}b];"
            f"[{p}a]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},boxblur=24:4,eq=brightness=-0.08[{p}f];"
            f"[{p}b]scale={largura}:-2[{p}g];[{p}f][{p}g]overlay=(W-w)/2:(H-h)/2,setsar=1[{sai}]")
