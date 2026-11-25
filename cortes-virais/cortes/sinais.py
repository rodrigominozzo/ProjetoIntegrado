"""Sinais de viralidade por segundo e escolha das melhores janelas de corte.

Três sinais, cada um medido contra a linha de base local do próprio vídeo:
  chat   — ritmo de mensagens (com peso extra para reações empolgadas)
  audio  — volume (gritos, risadas, torcida)
  replay — gráfico "mais repetidos" do YouTube, quando existe
"""
from __future__ import annotations

import collections
import subprocess
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from . import chat as chat_mod

TAXA = 8000  # Hz usados só para medir volume


def volume_por_segundo(arquivo: str | Path, inicio: float | None = None,
                       duracao: float | None = None) -> np.ndarray:
    """RMS em dB de cada segundo do áudio (do arquivo inteiro ou de um trecho)."""
    trecho = []
    if inicio is not None:
        trecho += ["-ss", f"{inicio:.2f}"]
    if duracao is not None:
        trecho += ["-t", f"{duracao:.2f}"]
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", *trecho, "-i", str(arquivo), "-vn", "-ac", "1", "-ar", str(TAXA),
         "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
    )
    valores = []
    while True:
        bloco = proc.stdout.read(TAXA * 2)
        if len(bloco) < TAXA:  # descarta resto menor que meio segundo
            break
        amostras = np.frombuffer(bloco[: len(bloco) // 2 * 2], dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(amostras ** 2))) + 1.0
        valores.append(20 * np.log10(rms / 32768))
    proc.wait()
    return np.array(valores, dtype=np.float32)


def chat_por_segundo(mensagens: list[tuple[float, str]], duracao: int, atraso: float) -> np.ndarray:
    """Mensagens ponderadas por segundo, adiantadas pelo atraso de reação do chat."""
    serie = np.zeros(duracao, dtype=np.float32)
    for t, texto in mensagens:
        i = int(t - atraso)
        if 0 <= i < duracao:
            serie[i] += chat_mod.peso(texto)
    return serie


def replay_por_segundo(replay: list[dict], duracao: int) -> np.ndarray:
    serie = np.zeros(duracao, dtype=np.float32)
    for p in replay:
        a, b = int(p["start_time"]), min(duracao, int(np.ceil(p["end_time"])))
        serie[a:b] = p["value"]
    return serie


def suavizar(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same") if len(x) >= n else x


def destaque(x: np.ndarray, janela: int = 300) -> np.ndarray:
    """Quanto cada segundo se destaca da mediana local (z robusto, só picos positivos)."""
    n = len(x)
    if n == 0:
        return x
    meio = min(janela // 2, max(1, (n - 1) // 2))
    xp = np.pad(x, meio, mode="edge")
    visao = sliding_window_view(xp, 2 * meio + 1)
    passo = max(1, n // 4000)  # amostra a linha de base em vídeos longos
    idx = np.arange(0, n, passo)
    mediana = np.median(visao[idx], axis=1)
    mad = np.median(np.abs(visao[idx] - mediana[:, None]), axis=1)
    mediana, mad = np.interp(np.arange(n), idx, mediana), np.interp(np.arange(n), idx, mad)
    piso = max(0.5 * float(np.std(x)), 1e-3)  # evita explosão em trechos constantes
    z = (x - mediana) / np.maximum(1.4826 * mad, piso)
    return np.clip(z, 0, 8).astype(np.float32)


def combinar(sinais: dict[str, np.ndarray], pesos: dict[str, float]) -> np.ndarray:
    """Mistura a média ponderada com o sinal mais forte de cada segundo: sinais que
    concordam se reforçam, mas um pico claro em um só deles não é diluído."""
    presentes = {k: v for k, v in sinais.items() if v is not None and len(v) and float(np.max(v)) > 0}
    if not presentes:
        raise ValueError("Nenhum sinal disponível para analisar o vídeo.")
    n = min(len(v) for v in presentes.values())
    total = sum(pesos.get(k, 1.0) for k in presentes)
    media = sum(pesos.get(k, 1.0) * v[:n] for k, v in presentes.items()) / total
    maior = np.max([v[:n] for v in presentes.values()], axis=0)
    return (media + maior) / 2


def melhores_janelas(pontuacao: np.ndarray, duracao: int, quantidade: int,
                     intervalo: int) -> list[tuple[int, float]]:
    """Inícios (em segundos) das janelas de maior pontuação média, sem sobreposição."""
    n = len(pontuacao)
    if n <= duracao:
        return [(0, float(np.mean(pontuacao)))] if n else []
    acumulado = np.concatenate([[0.0], np.cumsum(pontuacao, dtype=np.float64)])
    medias = (acumulado[duracao:] - acumulado[:-duracao]) / duracao
    afastamento = max(intervalo, duracao)
    escolhidas: list[tuple[int, float]] = []
    disponivel = medias.copy()
    while len(escolhidas) < quantidade:
        i = int(np.argmax(disponivel))
        if disponivel[i] <= 0:
            break
        escolhidas.append((i, float(medias[i])))
        disponivel[max(0, i - afastamento + 1): i + afastamento] = -1
    return escolhidas


def ajustar_ao_pico(pontuacao: np.ndarray, inicio: float, duracao: float, *, extra_fim: int = 20,
                   extra_inicio: int = 8, depois_do_pico: int = 8, antes_do_pico: int = 6,
                   fracao: float = 0.5, respiro: int = 3) -> tuple[float, float]:
    """A janela de maior média costuma terminar com a empolgação ainda no alto (o corte
    acabava antes de o pico baixar, sem a reação e a explicação que vêm depois). Aqui:
    - o fim vai pelo menos `depois_do_pico` segundos além do ponto mais alto;
    - se a curva (suavizada) ainda está alta no fim, estende até ela baixar, mais um respiro;
    - se a janela já começa com a curva alta, recua até onde ela começou a subir.
    Alta = acima de `fracao` do pico da janela. Devolve (início, fim) em segundos."""
    serie = np.asarray(pontuacao, dtype=np.float64)
    n = len(serie)
    ini, fim = max(0, int(inicio)), min(n, int(round(inicio + duracao)))
    if n == 0 or fim <= ini:
        return float(inicio), float(inicio + duracao)
    suave = np.convolve(serie, np.ones(5) / 5, mode="same")  # ignora quedas de 1–2 s no meio do pico
    pos_pico = ini + int(np.argmax(serie[ini:fim]))
    alto = fracao * float(suave[ini:fim].max())
    if alto <= 0:
        return float(ini), float(fim)
    limite_fim = min(n, fim + extra_fim)
    fim = min(limite_fim, max(fim, pos_pico + depois_do_pico))
    estendeu = False
    while fim < limite_fim and suave[fim - 1] >= alto:
        fim += 1
        estendeu = True
    if estendeu:
        fim = min(n, fim + respiro)
    limite_ini = max(0, ini - extra_inicio)
    ini = max(limite_ini, min(ini, pos_pico - antes_do_pico))
    while ini > limite_ini and suave[ini] >= alto:
        ini -= 1
    return float(ini), float(fim)


def analisar(*, audio: np.ndarray | None, mensagens: list[tuple[float, str]] | None,
             replay: list[dict] | None, duracao: float, cfg: dict) -> tuple[np.ndarray, dict]:
    """Pontuação por segundo e os sinais normalizados que a compõem."""
    n = int(duracao)
    sinais: dict[str, np.ndarray] = {}
    if audio is not None and len(audio):
        sinais["audio"] = destaque(suavizar(audio, 3))
        n = min(n, len(audio)) if n else len(audio)
    if mensagens:
        bruto = chat_por_segundo(mensagens, n, cfg["sinais"]["atraso_chat"])
        sinais["chat"] = destaque(suavizar(bruto, 5))
    if replay:
        sinais["replay"] = destaque(replay_por_segundo(replay, n), janela=max(300, n))
    return suavizar(combinar(sinais, cfg["sinais"]["pesos"]), 3), sinais


class DetectorPico:
    """Detecção em tempo real: dispara quando chat e/ou áudio saltam sobre a linha de base."""

    def __init__(self, limiar: float, espera: float, min_mensagens: float,
                 janela: float = 10, base: float = 300, aquecimento: float = 60,
                 pesos: dict | None = None):
        self.limiar, self.espera, self.min_mensagens = limiar, espera, min_mensagens
        self.janela, self.base, self.aquecimento = janela, base, aquecimento
        self.pesos = pesos or {"chat": 1.0, "audio": 0.6}
        self._hist: collections.deque[tuple[float, float, float | None]] = collections.deque()
        self._ultimo = -1e18
        self._inicio: float | None = None
        self.nivel = 0.0  # última pontuação calculada (para acompanhamento visual)

    @staticmethod
    def _z(atual: float, base: list[float], piso: float) -> float:
        if len(base) < 5:
            return 0.0
        mediana = float(np.median(base))
        mad = float(np.median(np.abs(np.array(base) - mediana)))
        return (atual - mediana) / max(1.4826 * mad, piso)

    def alimentar(self, t: float, chat: float, audio_db: float | None) -> float | None:
        """Recebe o chat ponderado desde a última chamada e o volume atual.

        Devolve a pontuação quando há um pico; senão None.
        """
        if self._inicio is None:
            self._inicio = t
        self._hist.append((t, chat, audio_db))
        while self._hist and self._hist[0][0] < t - self.base - self.janela:
            self._hist.popleft()
        recentes = [h for h in self._hist if h[0] > t - self.janela]
        antigos = [h for h in self._hist if h[0] <= t - self.janela]
        if t - self._inicio < self.aquecimento or not antigos:
            return None

        # Chat: soma na janela atual contra somas de janelas anteriores.
        chat_atual = sum(h[1] for h in recentes)
        blocos: dict[int, float] = collections.defaultdict(float)
        for ht, hc, _ in antigos:
            blocos[int((t - self.janela - ht) // self.janela)] += hc
        base_chat = list(blocos.values())
        z_chat = 0.0
        if chat_atual >= self.min_mensagens:
            z_chat = self._z(chat_atual, base_chat, (float(np.median(base_chat)) + 1) ** 0.5)

        # Áudio: média dos últimos segundos contra o histórico.
        sons = [h[2] for h in recentes if h[2] is not None][-3:]
        base_som = [h[2] for h in antigos if h[2] is not None]
        z_som = self._z(float(np.mean(sons)), base_som, 1.5) if sons else None

        if z_som is None:
            nota = z_chat
        else:
            pc, pa = self.pesos["chat"], self.pesos["audio"]
            # O sinal mais forte domina; o outro reforça.
            nota = max(z_chat, (pc * z_chat + pa * max(z_som, 0)) / (pc + pa) * 1.25)
            if not base_chat or max(base_chat) == 0:  # live sem chat: só áudio
                nota = max(z_som, 0)
        self.nivel = float(max(nota, 0))
        if nota >= self.limiar and t - self._ultimo >= self.espera:
            self._ultimo = t
            return float(nota)
        return None
