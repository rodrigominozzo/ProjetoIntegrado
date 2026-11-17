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


def filtro(layout: dict, w: int, h: int, largura: int = 1080, altura: int = 1920) -> str | None:
    """Trecho de filter_complex para o layout (sem rótulo de saída). None = usar blur."""
    tipo = layout["tipo"]
    if tipo == "rosto":
        r = layout["rosto"]
        return (f"[0:v]{_caixa(r['cx'] * w, h / 2, h * largura / altura, h, w, h)},"
                f"scale={largura}:{altura},setsar=1")
    if tipo == "dupla":
        meia = altura // 2
        cw = min(h * largura / meia, w * 0.5)
        ch = cw * meia / largura
        partes = []
        for nome, p in zip("tu", layout["pessoas"]):
            # rosto um pouco acima do centro do painel
            partes.append(f"[{nome}0]{_caixa(p['cx'] * w, p['cy'] * h + ch * 0.12, cw, ch, w, h)},"
                          f"scale={largura}:{meia},setsar=1[{nome}]")
        return f"[0:v]split[t0][u0];{partes[0]};{partes[1]};[t][u]vstack"
    if tipo == "facecam":
        r = layout["rosto"]
        topo = altura // 3
        cw = min(r["w"] * w * 3.4, w)
        ch = cw * topo / largura
        cam = _caixa(r["cx"] * w, r["cy"] * h + ch * 0.08, cw, ch, w, h)
        jogo = _caixa(w / 2, h / 2, h * largura / (altura - topo), h, w, h)
        return (f"[0:v]split[t0][u0];[t0]{cam},scale={largura}:{topo},setsar=1[t];"
                f"[u0]{jogo},scale={largura}:{altura - topo},setsar=1[u];[t][u]vstack")
    return None
