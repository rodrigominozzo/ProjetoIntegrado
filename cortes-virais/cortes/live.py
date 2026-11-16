"""Acompanhamento de live em tempo real.

O ffmpeg grava a live em segmentos curtos num buffer circular. A cada 2 s o detector
compara o ritmo do chat e o volume com a linha de base; quando há um pico, o trecho
[momento - pre, momento + pos] é recortado do buffer, avaliado, renderizado e publicado.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from . import chat as chat_mod
from . import fontes, ia, publicar, sinais, transcricao, vod
from .banco import Banco

log = logging.getLogger(__name__)
PASSO = 2.0
SEGMENTO = 4


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
        self.chat = chat if chat is not None else chat_mod.ChatAoVivo(url)
        self.detector = detector or sinais.DetectorPico(
            lv["limiar"], lv["espera"], lv["min_mensagens"], pesos=cfg["sinais"]["pesos"])
        self._volume: dict[int, float] = {}
        self._agendados: list[dict] = []
        self._trabalhos: list[threading.Thread] = []
        self.cortes: list[int] = []
        self._t0 = time.time()

    # --- captura ---
    def _iniciar_captura(self) -> subprocess.Popen:
        entrada = self._entrada or [
            "-i", fontes.url_do_fluxo(self.url, self.cfg["live"]["altura"]), "-c", "copy"]
        return subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", *entrada, "-f", "segment",
             "-segment_time", str(SEGMENTO), "-segment_format", "mpegts", "-strftime", "1",
             "-reset_timestamps", "1", str(self.buffer / "seg_%s.ts")],
            stdin=subprocess.DEVNULL)

    def _segmentos(self) -> list[tuple[int, Path]]:
        """(instante de início, arquivo) em ordem. O último ainda está sendo gravado."""
        return sorted((int(p.stem.split("_")[1]), p) for p in self.buffer.glob("seg_*.ts"))

    def _medir_volume(self, completos: list[tuple[int, Path]]) -> float | None:
        for inicio, arq in completos:
            if inicio not in self._volume:
                v = sinais.volume_por_segundo(arq)
                self._volume[inicio] = float(np.mean(v)) if len(v) else -90.0
        return self._volume[completos[-1][0]] if completos else None

    # --- recorte ---
    def _recortar(self, pedido: dict, segmentos: list[tuple[int, Path]], fim_buffer: float) -> None:
        a, b = pedido["a"], pedido["b"]
        fins = [s[0] for s in segmentos[1:]] + [fim_buffer]
        usados = [(ini, arq) for (ini, arq), fim in zip(segmentos, fins) if ini < b and fim > a]
        if not usados:
            log.warning("Buffer não cobre mais o pico de %s; corte perdido.", time.ctime(a))
            return
        bruto = self.pasta / f"bruto_{int(a)}.ts"
        lista = self.pasta / f"lista_{int(a)}.txt"
        lista.write_text("".join(f"file '{arq.resolve()}'\n" for _, arq in usados))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i",
                        str(lista), "-c", "copy", str(bruto)], check=True)
        lista.unlink()
        pedido.update(bruto=bruto, desloc=max(0.0, a - usados[0][0]))
        t = threading.Thread(target=self._produzir, args=(pedido,), daemon=True)
        t.start()
        self._trabalhos.append(t)

    def _produzir(self, pedido: dict) -> None:
        try:
            cfg = self.cfg
            dur = pedido["b"] - pedido["a"]
            ini_arq = pedido["desloc"]
            falas = transcricao.transcrever(pedido["bruto"], ini_arq, dur, cfg["idioma"],
                                            cfg["transcricao"]["whisper"])
            candidato = {
                "inicio": pedido["a"] - self._t0, "fim": pedido["b"] - self._t0,
                "inicio_arquivo": ini_arq, "fim_arquivo": ini_arq + dur,
                "pontuacao": pedido["nota"], "transcricao": transcricao.texto(falas),
                "chat": [m for _, m in pedido["mensagens"] if m][-25:],
            }
            avaliado = ia.avaliar([candidato], self.meta, pedido["bruto"], cfg)
            c = avaliado[0] if avaliado else None
            if not c or not c["aprovado"] or c["nota"] < cfg["ia"]["nota_minima"]:
                log.info("Pico descartado pela avaliação: %s", (c or {}).get("motivo", "sem resposta"))
                return
            self.cortes.append(vod.finalizar(c, pedido["bruto"], self.meta, cfg, self.banco,
                                             self.pasta, "live", falas, urgente=True))
            publicar.publicar_pendentes(cfg, self.banco)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao produzir corte da live")
        finally:
            Path(pedido["bruto"]).unlink(missing_ok=True)

    # --- laço principal ---
    def rodar(self, duracao_max: float | None = None) -> list[int]:
        lv = self.cfg["live"]
        self.banco.marcar_video(self.meta["id"], self.meta["titulo"], self.meta["canal"], "live")
        if hasattr(self.chat, "iniciar"):
            self.chat.iniciar()
        captura = self._iniciar_captura()
        log.info("Acompanhando live: %s", self.meta["titulo"])
        ultimo = time.time()
        try:
            while True:
                time.sleep(PASSO)
                agora = time.time()
                encerrou = captura.poll() is not None
                segs = self._segmentos()
                completos = segs if encerrou else segs[:-1]
                fim_buffer = agora if encerrou else (segs[-1][0] if segs else agora)

                novas = self.chat.desde(ultimo, agora)
                ultimo = agora
                nota = self.detector.alimentar(
                    agora, sum(chat_mod.peso(m) for _, m in novas), self._medir_volume(completos))
                if nota is not None:
                    momento = agora - self.cfg["sinais"]["atraso_chat"]
                    log.info("Pico detectado (%.1f) às %s", nota, time.strftime("%H:%M:%S"))
                    self._agendados.append({
                        "a": momento - lv["pre"], "b": momento + lv["pos"], "nota": nota,
                        "mensagens": self.chat.desde(momento - lv["pre"], agora)})

                # Recorta os picos cujo trecho já está inteiro no buffer.
                prontos = [p for p in self._agendados if p["b"] <= fim_buffer or encerrou]
                for p in prontos:
                    self._agendados.remove(p)
                    self._recortar(p, completos, fim_buffer)

                # Buffer circular: apaga o que ficou velho e não está reservado.
                corte_min = agora - lv["buffer_min"] * 60
                reservado = min((p["a"] for p in self._agendados), default=agora) - SEGMENTO
                for inicio, arq in completos:
                    if inicio < min(corte_min, reservado):
                        arq.unlink(missing_ok=True)
                        self._volume.pop(inicio, None)

                if duracao_max and agora - self._t0 >= duracao_max:
                    break
                if encerrou:
                    if self._entrada or not self._ainda_ao_vivo():
                        break
                    log.info("Captura caiu; reconectando.")
                    captura = self._iniciar_captura()
        finally:
            if captura.poll() is None:
                captura.terminate()
                captura.wait(timeout=10)
            if hasattr(self.chat, "parar"):
                self.chat.parar()
            for t in self._trabalhos:
                t.join(timeout=600)
            for p in self.buffer.glob("seg_*.ts"):
                p.unlink(missing_ok=True)
            self.banco.marcar_video(self.meta["id"], self.meta["titulo"], self.meta["canal"],
                                    "live_encerrada")
        log.info("Live encerrada: %d cortes gerados.", len(self.cortes))
        return self.cortes

    def _ainda_ao_vivo(self) -> bool:
        try:
            return fontes.info(self.url)["ao_vivo"]
        except Exception:  # noqa: BLE001
            return False
