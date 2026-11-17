"""Edição dinâmica do corte: decide, segundo a segundo, o que mostrar.

Técnicas aplicadas (todas configuráveis em `edicao`):
  - troca de plano a cada poucos segundos, para a imagem nunca ficar parada;
  - em gameplay com facecam: abre no rosto do jogador, alterna tela dividida e jogo
    em tela cheia, e volta ao rosto no momento-chave (a reação);
  - em vídeo de uma pessoa: cortes com zoom (punch-in), mais fechado no momento-chave;
  - corte seco das pausas longas de fala;
  - abertura pelo pico: 1,5 s do melhor momento antes de o corte começar.

O plano é uma lista de pedaços (início e fim no vídeo de origem, vista, zoom), na ordem
em que aparecem no corte final.
"""
from __future__ import annotations

import numpy as np

from . import enquadramento

PASSO = 0.1  # resolução da linha do tempo, em segundos

# Ciclos de planos por tipo de cena: (vista, zoom, duração em segundos)
CICLOS = {
    "facecam": [("dividido", 1.0, 5.5), ("jogo", 1.0, 3.5)],
    "rosto": [("rosto", 1.0, 4.5), ("rosto", 1.18, 3.5)],
    "dupla": [("dupla", 1.0, 999)],
    "blur": [("blur", 1.0, 999)],
}
# Plano do momento-chave: (vista, zoom, segundos antes, segundos depois)
DESTAQUE = {
    "facecam": ("reacao", 1.0, 0.4, 2.2),
    "rosto": ("rosto", 1.32, 0.2, 2.0),
    "blur": ("preencher", 1.0, 0.3, 2.5),
}


def faixas_de_fala(palavras: list, inicio: float, fim: float, pausa_minima: float) -> list[tuple[float, float]]:
    """Trechos do vídeo de origem que ficam, descartando as pausas longas entre falas."""
    falas = [p for p in palavras if inicio <= p[0] < fim]
    if len(falas) < 8:  # pouca fala: o conteúdo é a imagem, não mexe
        return [(inicio, fim)]
    folga = 0.25
    faixas, a = [], inicio
    if falas[0][0] - inicio > 1.0:  # começa direto na primeira fala
        a = falas[0][0] - 0.3
    for anterior, proxima in zip(falas, falas[1:]):
        if proxima[0] - anterior[1] >= pausa_minima:
            faixas.append((a, min(anterior[1] + folga, fim)))
            a = proxima[0] - folga
    faixas.append((a, fim))
    return [(x, y) for x, y in faixas if y - x > 0.3]


def planejar(layout: dict, inicio: float, fim: float, *, palavras: list | None = None,
             energia: np.ndarray | None = None, momento: float | None = None,
             abrir_com_pico: bool = False, cfg: dict | None = None) -> dict:
    """Monta o plano de edição. `momento` é o instante-chave no vídeo de origem (ou None
    para usar o pico de volume). Devolve {"pedacos", "flash", "duracao", "momento"}."""
    cfg = cfg or {}
    tipo = layout["tipo"]
    palavras = palavras or []
    fala_conduz = tipo != "facecam"  # em gameplay o silêncio de fala não é tempo morto
    faixas = [(inicio, fim)]
    if cfg.get("cortar_silencios", True) and fala_conduz:
        faixas = faixas_de_fala(palavras, inicio, fim, cfg.get("pausa_minima", 1.2))

    # Tempo de saída <-> tempo de origem.
    inicios_saida, total = [], 0.0
    for a, b in faixas:
        inicios_saida.append(total)
        total += b - a

    def para_saida(t: float) -> float:
        for (a, b), s in zip(faixas, inicios_saida):
            if t < a:
                return s
            if t <= b:
                return s + t - a
        return total

    if momento is None and energia is not None and len(energia) > 4:
        momento = inicio + 2 + int(np.argmax(energia[2:])) + 0.5
    momento = None if momento is None else min(max(momento, inicio), fim)

    # Linha do tempo de saída: um rótulo (vista, zoom) por décimo de segundo.
    n = max(1, int(round(total / PASSO)))
    base = enquadramento.VISTA_BASE[tipo]
    linha: list[tuple[str, float]] = [(base, 1.0)] * n
    if cfg.get("dinamica", True):
        pausas = [para_saida(p[0]) for i, p in enumerate(palavras[1:], 1)
                  if inicio <= p[0] < fim and p[0] - palavras[i - 1][1] >= 0.25]
        t, k, ciclo = 0.0, 0, CICLOS[tipo]
        while t < total:
            vista, zoom, dur = ciclo[k % len(ciclo)]
            alvo = t + dur
            perto = [x for x in pausas if abs(x - alvo) <= 0.7]  # troca de plano numa pausa
            prox = min(perto, key=lambda x: abs(x - alvo)) if perto else alvo
            for i in range(int(t / PASSO), min(n, int(prox / PASSO))):
                linha[i] = (vista, zoom)
            t, k = max(prox, t + 1.0), k + 1
        if tipo == "facecam" and cfg.get("abrir_no_rosto", True):
            for i in range(min(n, int(1.6 / PASSO))):  # rosto é o que mais segura a rolagem
                linha[i] = ("reacao", 1.0)
        if momento is not None and tipo in DESTAQUE:
            vista, zoom, antes, depois = DESTAQUE[tipo]
            m = para_saida(momento)
            for i in range(max(0, int((m - antes) / PASSO)), min(n, int((m + depois) / PASSO))):
                linha[i] = (vista, zoom)

    # Agrupa rótulos iguais em segmentos; os curtos demais se juntam ao anterior.
    segmentos: list[list] = []
    for i, rotulo in enumerate(linha):
        if segmentos and segmentos[-1][2] == rotulo:
            segmentos[-1][1] = (i + 1) * PASSO
        else:
            segmentos.append([i * PASSO, (i + 1) * PASSO, rotulo])
    limpos: list[list] = []
    for seg in segmentos:
        if limpos and seg[1] - seg[0] < 0.7:
            limpos[-1][1] = seg[1]
        elif limpos and limpos[-1][2] == seg[2]:
            limpos[-1][1] = seg[1]
        else:
            limpos.append(seg)
    limpos[-1][1] = total

    # Volta ao tempo de origem, quebrando onde há corte de silêncio.
    pedacos = []
    for sa, sb, (vista, zoom) in limpos:
        for (a, b), s in zip(faixas, inicios_saida):
            x, y = max(sa, s), min(sb, s + (b - a))
            if y - x > 0.05:
                pedacos.append({"a": a + x - s, "b": a + y - s, "vista": vista, "zoom": zoom})

    flash = None
    if abrir_com_pico and cfg.get("abertura_pico", True) and momento and momento - inicio > 6:
        vista, zoom = DESTAQUE.get(tipo, (base, 1.0, 0, 0))[:2]
        previa = {"a": momento - 0.3, "b": min(momento + 1.4, fim), "vista": vista, "zoom": zoom}
        pedacos.insert(0, previa)
        flash = previa["b"] - previa["a"]
    return {"pedacos": pedacos, "flash": flash, "momento": momento,
            "duracao": sum(p["b"] - p["a"] for p in pedacos)}


def remapear(palavras: list, pedacos: list[dict]) -> list:
    """Leva as palavras do tempo de origem para o tempo do corte final (começando em 0)."""
    saida, t = [], 0.0
    for p in pedacos:
        for a, b, texto in palavras:
            if p["a"] - 0.05 <= a < p["b"]:
                saida.append((t + a - p["a"], t + min(b, p["b"]) - p["a"], texto))
        t += p["b"] - p["a"]
    return saida


def grafo(plano: dict, layout: dict, inicio: float, w: int, h: int, tem_audio: bool,
          largura: int = 1080, altura: int = 1920) -> str:
    """filter_complex que monta os pedaços; saídas [vc] (vídeo) e, havendo áudio, [ac]."""
    pedacos = plano["pedacos"]
    n = len(pedacos)
    partes = [f"[0:v]fps=30,split={n}" + "".join(f"[i{k}]" for k in range(n))]
    for k, p in enumerate(pedacos):
        partes.append(f"[i{k}]trim=start={p['a'] - inicio:.3f}:end={p['b'] - inicio:.3f},"
                      f"setpts=PTS-STARTPTS[c{k}]")
        partes.append(enquadramento.cadeia(p["vista"], layout, w, h, p["zoom"], f"c{k}", f"v{k}",
                                           f"s{k}", largura, altura))
    partes.append("".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[vc]")
    if tem_audio:
        # Áudio: só é cortado onde a imagem salta no tempo (pedaços contíguos seguem juntos).
        faixas: list[list[float]] = []
        for p in pedacos:
            if faixas and abs(faixas[-1][1] - p["a"]) < 0.01:
                faixas[-1][1] = p["b"]
            else:
                faixas.append([p["a"], p["b"]])
        m = len(faixas)
        partes.append(f"[0:a:0]asplit={m}" + "".join(f"[j{k}]" for k in range(m)))
        for k, (a, b) in enumerate(faixas):
            partes.append(f"[j{k}]atrim=start={a - inicio:.3f}:end={b - inicio:.3f},"
                          f"asetpts=PTS-STARTPTS,afade=t=in:d=0.02[a{k}]")
        partes.append("".join(f"[a{k}]" for k in range(m)) + f"concat=n={m}:v=0:a=1[ac]")
    return ";".join(partes)
