"""Acompanhamento de live em tempo real.

O ffmpeg grava a live em segmentos curtos num buffer circular. A cada 2 s o detector
compara o ritmo do chat e o volume com a linha de base; quando há um pico, o trecho
[momento - pre, momento + pos] é recortado do buffer, avaliado, renderizado e publicado.
"""
from __future__ import annotations

import collections
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from . import chat as chat_mod
from . import desempenho, fontes, historico, ia, publicar, sinais, transcricao, vod
from .banco import Banco

log = logging.getLogger(__name__)
PASSO = 2.0
SEGMENTO = 4


def limiar_da_live(titulo: str, lv: dict) -> float:
    """Limiar de empolgação desta live: o menor (live.limiar_menor) quando o título tem
    alguma das palavras de live.palavras_limiar_menor (ex.: "GTA"), senão o normal."""
    palavras = [p.strip().lower() for p in str(lv.get("palavras_limiar_menor") or "").split(",")
                if p.strip()]
    titulo = (titulo or "").lower()
    if palavras and lv.get("limiar_menor") and any(p in titulo for p in palavras):
        return float(min(lv["limiar_menor"], lv["limiar"]))
    return float(lv["limiar"])


def _fim_da_imagem(arquivo: Path) -> float | None:
    """Segundo (a partir do começo do arquivo) do último quadro de imagem, ou None."""
    try:
        saida = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "packet=pts_time,duration_time", "-of", "csv=p=0", str(arquivo)],
            capture_output=True, text=True, timeout=60).stdout
        primeiro = fim = None
        for linha in saida.splitlines():
            partes = linha.split(",")
            try:
                t = float(partes[0])
            except (ValueError, IndexError):
                continue
            d = float(partes[1]) if len(partes) > 1 and partes[1] not in ("", "N/A") else 0.0
            primeiro = t if primeiro is None else min(primeiro, t)
            fim = t + d if fim is None else max(fim, t + d)
        if fim is None:
            return None
        inicio = _inicio_do_arquivo(arquivo)
        return fim - (inicio if inicio is not None else (primeiro or 0.0))
    except (OSError, subprocess.SubprocessError):
        return None


def _inicio_do_arquivo(arquivo: Path) -> float | None:
    """Início do arquivo (o menor início entre vídeo e som), a referência dos tempos."""
    try:
        saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=start_time",
                                "-of", "csv=p=0", str(arquivo)],
                               capture_output=True, text=True, timeout=30).stdout.strip()
        return float(saida)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


class MonitorLive:
    def __init__(self, url: str, cfg: dict, banco: Banco, *, meta: dict | None = None,
                 entrada_ffmpeg: list[str] | None = None, chat=None, detector=None):
        self.url, self.cfg, self.banco = url, cfg, banco
        self.meta = meta or fontes.info(url)
        self.meta["ao_vivo"] = True
        self._entrada = entrada_ffmpeg  # usado em testes/simulação no lugar da live real
        self.pasta = Path(cfg["pasta_trabalho"]) / f"live_{self.meta['id']}"
        self.buffer = self.pasta / "buffer"
        self.buffer.mkdir(parents=True, exist_ok=True)
        lv = cfg["live"]
        self.limiar = limiar_da_live(self.meta.get("titulo", ""), lv)
        self.chat = chat if chat is not None else chat_mod.para_live(url, self.meta["id"])
        self.detector = detector or sinais.DetectorPico(
            self.limiar, lv["espera"], lv["min_mensagens"], pesos=cfg["sinais"]["pesos"])
        self._volume: dict[str, float] = {}
        self._agendados: list[dict] = []
        self._trabalhos: list[threading.Thread] = []
        self._t0 = time.time()
        self._geracao = 0
        self._vistos: dict[str, float] = {}
        self._defasagens: dict[int, float] = {}
        self._parar = threading.Event()
        self.parado_pelo_usuario = False
        self.terminou = False  # a live acabou de verdade (não foi só o programa fechando)
        # Progresso guardado em disco: ao reabrir o programa, a live continua de onde estava.
        self.progresso = historico.Progresso(self.pasta)
        if self.progresso.d["inicio"] is None:
            self.progresso.d["inicio"] = self._t0
        self.cortes: list[int] = [c["id"] for c in banco.cortes_do_video(self.meta["id"])
                                  if c["origem"] == "live"]
        # Retrato do andamento, lido pelo painel.
        self.estado = {
            "status": "conectando", "inicio": self._t0, "limiar": self.limiar, "nivel": 0.0,
            "historico": collections.deque(maxlen=150), "mensagens_min": 0,
            "chat_ativo": False, "picos": [], "erro": "",
        }
        anteriores = self.progresso.d["picos"][-20:]
        for p in anteriores:
            if p.get("resultado") == "Recortando…":
                p["resultado"] = "Interrompido: o programa foi fechado enquanto recortava"
        self.estado["picos"] = anteriores
        if self.progresso.d["inicio"]:
            self.estado["inicio"] = self.progresso.d["inicio"]

    def parar(self) -> None:
        self._parar.set()

    # --- captura ---
    # Os pedaços são escolhidos pelo TEMPO DO VÍDEO, não pelo relógio: o YouTube entrega a
    # live em rajadas (um pedaço de 7 s de imagem pode ocupar 11 s de relógio), e escolher
    # pelo relógio pedia trechos além do fim do arquivo — a imagem acabava antes do som.
    # O ffmpeg anota em lista_N.csv o início e o fim de cada pedaço, em tempo do vídeo.
    # Os pedaços são numerados em sequência: com o nome pelo horário, dois pedaços que
    # começavam no mesmo segundo (comum nas rajadas) tinham o mesmo nome e o segundo
    # apagava o primeiro — o corte repetia 5 s, perdia outros 5 s e "travava".
    def _iniciar_captura(self) -> subprocess.Popen:
        entrada = self._entrada or fontes.entrada_ffmpeg_live(
            fontes.url_do_fluxo(self.url, self.cfg["live"]["altura"]))
        self._geracao += 1  # cada (re)conexão recomeça o tempo do vídeo do zero
        self._vistos = {}
        # O log (nível info) guarda onde cada transmissão começou: é dele que sai a
        # defasagem entre vídeo e áudio separados, corrigida ao montar o corte.
        self._fechar_registro()
        registro = open(self.buffer / f"ffmpeg_{self._geracao}.log", "w", encoding="utf-8",  # noqa: SIM115
                        errors="replace")
        self._registro = registro
        return subprocess.Popen(
            ["ffmpeg", "-v", "info", "-nostats", "-hide_banner", "-y", *entrada, "-f", "segment",
             "-segment_time", str(SEGMENTO), "-segment_format", "mpegts",
             "-reset_timestamps", "1",
             "-segment_list", str(self.buffer / f"lista_{self._geracao}.csv"),
             "-segment_list_type", "csv",
             str(self.buffer / f"seg_g{self._geracao}_%06d.ts")],
            stdin=subprocess.DEVNULL, stderr=registro)

    def _fechar_registro(self) -> None:
        if getattr(self, "_registro", None):
            try:
                self._registro.close()
            except OSError:
                pass
            self._registro = None

    def _defasagem(self, geracao: int) -> float:
        """Quanto o áudio começou depois do vídeo na transmissão (segundos; negativo se antes),
        para a captura `geracao`. Vídeo e áudio separados vêm com o mesmo relógio, mas o
        ffmpeg zera cada um a partir do próprio começo: sem esta correção, o corte inteiro
        fica com o som defasado (na live do Cellbit eram 5 s)."""
        if geracao in self._defasagens:
            return self._defasagens[geracao]
        try:
            texto = (self.buffer / f"ffmpeg_{geracao}.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0.0
        inicios = {int(n): float(t) for n, t in re.findall(
            r"Input #(\d+),.*?\n\s+Duration:[^\n]*?start: (-?[\d.]+)", texto, re.S)}
        if 0 not in inicios:
            return 0.0  # o ffmpeg ainda não abriu as entradas
        valor = inicios[1] - inicios[0] if 1 in inicios else 0.0
        self._defasagens[geracao] = valor
        if abs(valor) > 0.05:
            log.info("Live %s: áudio %.2f s %s do vídeo na transmissão; corrigido nos cortes.",
                     self.meta["id"], abs(valor), "depois" if valor > 0 else "antes")
        return valor

    def _segmentos(self) -> list[tuple[float, Path]]:
        """(horário da última gravação, arquivo) em ordem de captura. O último ainda está
        sendo gravado."""
        def ordem(arq: Path) -> tuple[int, int]:
            g, n = arq.stem.split("_")[1:3]
            return int(g.lstrip("g") or 0), int(n)
        itens = []
        for arq in self.buffer.glob("seg_g*_*.ts"):
            try:
                itens.append((ordem(arq), arq.stat().st_mtime, arq))
            except (OSError, ValueError):
                continue
        return [(t, arq) for _, t, arq in sorted(itens)]

    def _midia(self) -> list[tuple[Path, float, float]]:
        """Pedaços prontos da captura atual: (arquivo, início, fim) em tempo do vídeo. Guarda
        também o horário em que cada um apareceu, para ligar o relógio ao tempo do vídeo."""
        lista = self.buffer / f"lista_{self._geracao}.csv"
        saida = []
        try:
            linhas = lista.read_text(encoding="utf-8").splitlines()
        except OSError:
            return saida
        for linha in linhas:
            partes = linha.rsplit(",", 2)
            if len(partes) != 3:
                continue
            arq = self.buffer / Path(partes[0]).name
            try:
                ini, fim = float(partes[1]), float(partes[2])
            except ValueError:
                continue
            self._vistos.setdefault(arq.name, time.time())
            if arq.exists():
                saida.append((arq, ini, fim))
        return saida

    def _tempo_do_video(self, relogio: float, midia: list[tuple[Path, float, float]]) -> float | None:
        """Em que segundo do vídeo capturado estava o instante `relogio`: o fim do pedaço
        mais novo corresponde (com erro de ~2 s) ao horário em que ele apareceu."""
        if not midia:
            return None
        arq, _, fim = midia[-1]
        return fim - (self._vistos.get(arq.name, time.time()) - relogio)

    def _medir_volume(self, completos: list[tuple[float, Path]]) -> float | None:
        for _, arq in completos:
            if arq.name not in self._volume:
                v = sinais.volume_por_segundo(arq)
                self._volume[arq.name] = float(np.mean(v)) if len(v) else -90.0
        return self._volume[completos[-1][1].name] if completos else None

    # --- recorte ---
    def _recortar(self, pedido: dict, midia: list[tuple[Path, float, float]]) -> None:
        a = pedido["a"]
        ma, mb = pedido["ma"], pedido["mb"]
        usados = ([(arq, ini, fim) for arq, ini, fim in midia if ini < mb and fim > ma]
                  if pedido["geracao"] == self._geracao else [])
        if not usados:
            log.warning("Buffer não cobre mais o pico de %s; corte perdido.", time.ctime(a))
            pedido["pico"]["resultado"] = "Perdido: o trecho já tinha saído do buffer"
            return
        # MP4, não TS: o TS não tem índice e a renderização, ao pular para o início do corte,
        # caía alguns segundos fora do lugar só na imagem (o corte saía com 3 s a menos de
        # vídeo que de som). No MP4 o pulo é exato.
        bruto = self.pasta / f"bruto_{int(a)}.mp4"
        lista = self.pasta / f"lista_{int(a)}.txt"
        lista.write_text("".join(f"file '{arq.resolve()}'\n" for arq, _, _ in usados), encoding="utf-8")
        concat = ["-f", "concat", "-safe", "0", "-i", str(lista)]
        d = self._defasagem(pedido["geracao"])
        if abs(d) > 0.05:  # atrasa a faixa que começou antes, para as duas baterem
            vid = ["-itsoffset", f"{-d:.3f}"] if d < 0 else []
            aud = ["-itsoffset", f"{d:.3f}"] if d > 0 else []
            entradas = [*vid, *concat, *aud, *concat, "-map", "0:v:0", "-map", "1:a:0"]
        else:
            entradas = concat
        subprocess.run(["ffmpeg", "-v", "error", "-y", *entradas, "-c", "copy",
                        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(bruto)],
                       check=True)
        lista.unlink()
        desloc = max(0.0, ma - usados[0][1])
        dur = min(mb, usados[-1][2]) - (usados[0][1] + desloc)  # nunca além do que foi gravado
        imagem = _fim_da_imagem(bruto)  # a lista conta pelo som, que vai um pouco além do vídeo
        if imagem is not None:
            dur = min(dur, imagem - desloc - 0.05)
        pedido.update(bruto=bruto, desloc=desloc, dur=max(1.0, dur))
        t = threading.Thread(target=self._produzir, args=(pedido,), daemon=True)
        t.start()
        self._trabalhos.append(t)

    def _produzir(self, pedido: dict) -> None:
        try:
            cfg = self.cfg
            dur = pedido["dur"]
            ini_arq = pedido["desloc"]
            falas = transcricao.transcrever(pedido["bruto"], ini_arq, dur, cfg["idioma"],
                                            cfg["transcricao"]["whisper"])
            candidato = {
                "inicio": pedido["a"] - self._t0, "fim": pedido["a"] - self._t0 + dur,
                "inicio_arquivo": ini_arq, "fim_arquivo": ini_arq + dur,
                "pontuacao": pedido["nota"], "transcricao": transcricao.texto(falas),
                "folga_inicio": min(8, ini_arq), "folga_fim": 0,  # o buffer acaba no fim do trecho
                "chat": [m for _, m in pedido["mensagens"] if m][-25:],
            }
            self.meta["referencias"] = desempenho.referencias(self.banco)
            avaliado = ia.avaliar([candidato], self.meta, pedido["bruto"], cfg)
            c = avaliado[0] if avaliado else None
            motivo = ia.motivo_descarte(c, cfg["ia"]["nota_minima"])
            if motivo:
                log.info("Pico descartado: %s", motivo)
                pedido["pico"]["resultado"] = f"Descartado: {motivo}"
                return
            self.cortes.append(vod.finalizar(c, pedido["bruto"], self.meta, cfg, self.banco,
                                             self.pasta, "live", falas, urgente=True))
            pedido["pico"]["resultado"] = f"Corte gerado: {c['titulo']}"
            publicar.publicar_pendentes(cfg, self.banco)
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao produzir corte da live")
            pedido["pico"]["resultado"] = f"Erro: {e}"
        finally:
            Path(pedido["bruto"]).unlink(missing_ok=True)

    # --- laço principal ---
    def rodar(self, duracao_max: float | None = None) -> list[int]:
        lv = self.cfg["live"]
        self.banco.marcar_video(self.meta["id"], self.meta["titulo"], self.meta["canal"], "live")
        if hasattr(self.chat, "iniciar"):
            self.chat.iniciar()
        for velho in [*self.buffer.glob("seg_*.ts"), *self.buffer.glob("lista_*.csv"),
                      *self.buffer.glob("ffmpeg_*.log")]:
            velho.unlink(missing_ok=True)  # sobras de uma sessão anterior (programa fechado)
        captura = self._iniciar_captura()
        log.info("Acompanhando live: %s (corta em %.1f)", self.meta["titulo"], self.limiar)
        passado = None
        if lv.get("historico", True) and not self._entrada:
            passado = threading.Thread(target=historico.AnalisePassado(self).rodar, daemon=True,
                                       name=f"passado-{self.meta['id']}")
            passado.start()
        self.estado["status"] = "acompanhando"
        self.progresso.abrir_cobertura(time.time())
        self.progresso.salvar()
        guardado = time.time()
        ultimo = time.time()
        recentes: collections.deque[float] = collections.deque()
        try:
            while not self._parar.wait(PASSO):
                agora = time.time()
                encerrou = captura.poll() is not None
                segs = self._segmentos()
                completos = segs if encerrou else segs[:-1]
                midia = self._midia()

                novas = self.chat.desde(ultimo, agora)
                ultimo = agora
                nota = self.detector.alimentar(
                    agora, sum(chat_mod.peso(m) for _, m in novas), self._medir_volume(completos))
                recentes.extend(t for t, _ in novas)
                while recentes and recentes[0] < agora - 60:
                    recentes.popleft()
                self.estado.update(nivel=round(self.detector.nivel, 2),
                                   mensagens_min=len(recentes),
                                   chat_ativo=bool(getattr(self.chat, "ativo", True)))
                self.estado["historico"].append(round(self.detector.nivel, 2))
                if nota is not None:
                    momento = agora - self.cfg["sinais"]["atraso_chat"]
                    log.info("Pico detectado (%.1f) às %s", nota, time.strftime("%H:%M:%S"))
                    pico = {"hora": agora, "nota": round(nota, 1), "resultado": "Recortando…"}
                    self.estado["picos"].append(pico)
                    m = self._tempo_do_video(momento, midia)
                    if m is None:
                        pico["resultado"] = "Perdido: a gravação ainda não tinha começado"
                    else:
                        self._agendados.append({
                            "a": momento - lv["pre"], "nota": nota, "pico": pico,
                            "geracao": self._geracao, "ma": max(0.0, m - lv["pre"]),
                            "mb": m + lv["pos"],
                            "mensagens": self.chat.desde(momento - lv["pre"], agora)})

                # Recorta os picos cujo trecho já está inteiro no buffer (em tempo do vídeo).
                gravado = midia[-1][2] if midia else 0.0
                prontos = [p for p in self._agendados
                           if encerrou or p["geracao"] != self._geracao or p["mb"] <= gravado]
                for p in prontos:
                    self._agendados.remove(p)
                    self._recortar(p, midia)

                # Buffer circular: apaga o que ficou velho e não está reservado.
                corte_min = agora - lv["buffer_min"] * 60
                reservado = min((p["a"] for p in self._agendados), default=agora) - 3 * SEGMENTO
                for inicio, arq in completos:
                    if inicio < min(corte_min, reservado):
                        arq.unlink(missing_ok=True)
                        self._volume.pop(arq.name, None)

                if agora - guardado >= 30:
                    self._guardar_progresso(agora)
                    guardado = agora
                if duracao_max and agora - self._t0 >= duracao_max:
                    break
                if encerrou:
                    if self._entrada or not self._ainda_ao_vivo():
                        self.terminou = True
                        break
                    log.info("Captura caiu; reconectando.")
                    captura = self._iniciar_captura()
        finally:
            if captura.poll() is None:
                captura.terminate()
                try:
                    captura.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    captura.kill()
            if hasattr(self.chat, "parar"):
                self.chat.parar()
            for t in self._trabalhos + ([passado] if passado else []):
                t.join(timeout=600)
            self._fechar_registro()
            for p in [*self.buffer.glob("seg_*.ts"), *self.buffer.glob("lista_*.csv"),
                      *self.buffer.glob("ffmpeg_*.log")]:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            self._guardar_progresso(time.time())
            if self.terminou or self.parado_pelo_usuario:
                # Acabou de vez: os pedaços de áudio do passado não servem mais.
                shutil.rmtree(self.pasta / "passado", ignore_errors=True)
            self.banco.marcar_video(self.meta["id"], self.meta["titulo"], self.meta["canal"],
                                    "live_encerrada")
            self.estado.update(status="encerrada", fim=time.time())
        log.info("Live encerrada: %d cortes gerados.", len(self.cortes))
        return self.cortes

    def _guardar_progresso(self, agora: float) -> None:
        self.progresso.estender_cobertura(agora)
        self.progresso.d["picos"] = [dict(p) for p in self.estado["picos"]][-20:]
        self.progresso.salvar()

    def _ainda_ao_vivo(self) -> bool:
        try:
            return fontes.info(self.url)["ao_vivo"]
        except Exception:  # noqa: BLE001
            return False
