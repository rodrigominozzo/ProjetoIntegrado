"""Análise do trecho de uma live que já tinha passado quando o acompanhamento começou.

Enquanto o MonitorLive segue a live em tempo real, esta segunda frente olha para trás: o
YouTube guarda a live desde o início em pedaços de ~5 s (numerados, "sq"), e a Twitch, na
gravação (VOD) que o canal vai gerando, em pedaços de 10 s. Baixamos só o
áudio do período (leve: ~80 KB por pedaço), medimos o volume segundo a segundo contra a
própria live inteira, e só dos melhores momentos baixamos o vídeo para a IA avaliar e
renderizar. Assim um começo já frenético não vira "ritmo normal" e o que aconteceu antes
do play também pode virar corte.

O chat do passado não fica disponível enquanto a live está no ar (o replay só aparece
quando ela termina), por isso aqui o sinal é o áudio.
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import time

import numpy as np
import requests
from yt_dlp.utils import update_url_query

from . import desempenho, fontes, ia, publicar, sinais, transcricao, vod

log = logging.getLogger(__name__)
SIMULTANEOS = 6


class FonteYouTube:
    """Live do YouTube desde o início: pedaços de ~5 s numerados ("sq"), com faixas de vídeo e
    de áudio separadas."""
    nome = "YouTube"
    video_com_audio = False

    def __init__(self, url: str, altura: int):
        with fontes._ydl({"skip_download": True, "live_from_start": True}) as ydl:
            d = ydl.extract_info(url, download=False, process=False)
        fs = [f for f in d.get("formats") or [] if f.get("is_from_start") and f.get("url")]
        audios = [f for f in fs if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
        videos = [f for f in fs if (f.get("vcodec") or "").startswith("avc1")
                  and f.get("acodec") in (None, "none") and (f.get("height") or 0) <= altura]
        if not audios or not videos:
            raise RuntimeError("o YouTube não oferece esta live desde o início "
                               "(o canal desligou a opção de voltar na transmissão)")
        audio = next((f for f in audios if f.get("format_id") == "140"),
                     max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0))
        video = max(videos, key=lambda f: ((f.get("height") or 0), f.get("tbr") or 0))
        self._base = {"a": audio["url"], "v": video["url"]}
        self.frag = float(audio.get("target_duration") or video.get("target_duration") or 5)

    def cabeca(self) -> int:
        """Número do pedaço mais recente (o "agora" da live)."""
        r = requests.head(self._base["a"], timeout=20, allow_redirects=True)
        try:
            return int(r.headers["X-Head-Seqnum"])
        except (KeyError, ValueError):
            raise RuntimeError("não consegui saber em que ponto a live está") from None

    def url(self, tipo: str, sq: int) -> str:
        return update_url_query(self._base[tipo], {"sq": str(sq)})

    def init(self, tipo: str, sq: int) -> str | None:
        return None  # cada pedaço do YouTube já traz o próprio cabeçalho


GQL_TWITCH = "https://gql.twitch.tv/gql"
CLIENT_ID_TWITCH = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # o do site público da Twitch


def login_twitch(url: str) -> str:
    m = re.search(r"twitch\.tv/(?!videos/)([A-Za-z0-9_]{2,25})", url or "")
    if not m:
        raise RuntimeError("não reconheci o canal da Twitch")
    return m.group(1).lower()


class FonteTwitch:
    """Live da Twitch pela gravação (VOD) que o canal vai gerando enquanto transmite: pedaços
    de 10 s numerados (0, 1, 2…), com uma faixa só de áudio e as de vídeo já com o som.
    Só existe se o canal guarda as transmissões."""
    nome = "Twitch"
    video_com_audio = True

    def __init__(self, url: str, altura: int):
        login = login_twitch(url)
        consulta = {"query": 'query{user(login:"%s"){stream{archiveVideo{id status}}}}' % login}
        r = requests.post(GQL_TWITCH, json=consulta, timeout=20,
                          headers={"Client-ID": CLIENT_ID_TWITCH})
        arquivo = ((((r.json().get("data") or {}).get("user") or {}).get("stream") or {})
                   .get("archiveVideo") or {})
        if not arquivo.get("id"):
            raise RuntimeError("o canal não guarda a gravação das lives na Twitch")
        self.vod = arquivo["id"]
        with fontes._ydl({"skip_download": True}) as ydl:
            d = ydl.extract_info(f"https://www.twitch.tv/videos/{self.vod}", download=False)
        fs = [f for f in d.get("formats") or [] if f.get("url")]
        audio = next((f for f in fs if f.get("vcodec") == "none"), None)
        videos = [f for f in fs if f.get("vcodec") not in (None, "none")
                  and (f.get("height") or 0) <= altura]
        if not audio or not videos:
            raise RuntimeError("a gravação desta live da Twitch não está disponível")
        video = max(videos, key=lambda f: ((f.get("height") or 0), f.get("fps") or 0))
        self._listas = {"a": audio["url"], "v": video["url"]}
        self._nomes: dict[str, list[str]] = {}
        self._inits: dict[str, list[str | None]] = {}
        self.frag = 10.0
        self._carregar("a")

    def _carregar(self, tipo: str) -> None:
        texto = requests.get(self._listas[tipo], timeout=30).text
        nomes, inits, init = [], [], None
        for linha in texto.splitlines():
            linha = linha.strip()
            if linha.startswith("#EXT-X-TARGETDURATION:"):
                self.frag = float(linha.split(":", 1)[1] or 10)
            elif linha.startswith("#EXT-X-MAP:"):
                m = re.search(r'URI="([^"]+)"', linha)
                init = m.group(1) if m else None
            elif linha and not linha.startswith("#"):
                nomes.append(linha)
                inits.append(init)
        self._nomes[tipo], self._inits[tipo] = nomes, inits

    def _base(self, tipo: str) -> str:
        return self._listas[tipo].rsplit("/", 1)[0]

    def cabeca(self) -> int:
        self._carregar("a")
        return len(self._nomes["a"])

    def url(self, tipo: str, sq: int) -> str:
        if tipo not in self._nomes or sq >= len(self._nomes[tipo]):
            self._carregar(tipo)
        return f"{self._base(tipo)}/{self._nomes[tipo][sq]}"

    def init(self, tipo: str, sq: int) -> str | None:
        if tipo not in self._inits or sq >= len(self._inits[tipo]):
            self._carregar(tipo)
        nome = self._inits[tipo][sq] if sq < len(self._inits[tipo]) else None
        return f"{self._base(tipo)}/{nome}" if nome else None


def fonte_do_passado(url: str, altura: int):
    """A fonte certa para olhar o que já passou da live."""
    if "twitch.tv" in (url or "").lower():
        return FonteTwitch(url, altura)
    return FonteYouTube(url, altura)


def _baixar_um(endereco: str, destino: Path) -> Path | None:
    if destino.exists() and destino.stat().st_size:
        return destino
    for tentativa in range(5):
        try:
            r = requests.get(endereco, timeout=30)
            if r.status_code == 200 and r.content:
                destino.write_bytes(r.content)
                return destino
        except requests.RequestException:
            pass
        threading.Event().wait(2 * (tentativa + 1))
    return None


def baixar(fonte, tipo: str, primeiro: int, ultimo: int, pasta: Path, prefixo: str,
           parar: threading.Event, progresso=None) -> list[Path]:
    """Baixa os pedaços [primeiro, ultimo) em paralelo. Pedaços que falharem ficam de fora."""
    pasta.mkdir(parents=True, exist_ok=True)
    total = max(1, ultimo - primeiro)
    feitos: dict[int, Path | None] = {}
    with ThreadPoolExecutor(SIMULTANEOS) as ex:
        futuros = {}
        for sq in range(primeiro, ultimo):
            if parar.is_set():
                break
            futuros[sq] = ex.submit(_baixar_um, fonte.url(tipo, sq), pasta / f"{prefixo}_{sq:07d}.mp4")
        for n, (sq, fut) in enumerate(futuros.items()):
            feitos[sq] = fut.result()
            if progresso and n % 20 == 0:
                progresso(n / total)
    return [feitos[sq] for sq in sorted(feitos) if feitos[sq]]


_cabecalhos: dict[str, bytes] = {}


def juntar(pedacos: list[Path], saida: Path, fonte=None, tipo: str = "a") -> Path:
    """Emenda os pedaços. Os do YouTube são MP4 fragmentados autossuficientes (basta emendar
    os bytes); os da Twitch dependem de um cabeçalho comum ("init"), posto antes do primeiro
    pedaço e de novo sempre que ele muda."""
    atual = None
    with open(saida, "wb") as f:
        for p in pedacos:
            if fonte is not None:
                init = fonte.init(tipo, int(p.stem.split("_")[1]))
                if init and init != atual:
                    if init not in _cabecalhos:
                        _cabecalhos[init] = requests.get(init, timeout=30).content
                    f.write(_cabecalhos[init])
                    atual = init
            with open(p, "rb") as e:
                shutil.copyfileobj(e, f)
    return saida


def diferenca_faixas(arquivo: Path) -> float:
    """Quantos segundos a faixa de vídeo e a de áudio diferem (início e fim). Num trecho
    bem montado é quase zero; segundos de diferença = corte com som fora de sincronia."""
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time,duration",
         "-of", "json", str(arquivo)], capture_output=True, text=True, timeout=60).stdout
    faixas = {s.get("codec_type"): s for s in json.loads(saida or "{}").get("streams", [])}
    if "video" not in faixas or "audio" not in faixas:
        return float("inf")
    def tempos(s):
        ini = float(s.get("start_time") or 0)
        return ini, ini + float(s.get("duration") or 0)
    (vi, vf), (ai, af) = tempos(faixas["video"]), tempos(faixas["audio"])
    return max(abs(vi - ai), abs(vf - af))


class Progresso:
    """O que já foi feito numa live, em disco, para sobreviver ao programa ser fechado:
    - cobertura: intervalos (horário do relógio) em que a frente em tempo real acompanhou;
    - avaliados: trechos [sq_a, sq_b] do passado que a IA já avaliou;
    - picos e início do acompanhamento, para o cartão da live continuar de onde estava.
    Ao reabrir, a segunda frente olha só o que ninguém viu (incluindo o tempo em que o
    programa ficou fechado) e não reavalia o que já avaliou."""

    MARGEM_S = 30  # folga ao comparar horários (o relógio da live e o daqui não batem exato)

    def __init__(self, pasta: Path):
        self.caminho = Path(pasta) / "progresso.json"
        self._trava = threading.Lock()
        try:
            self.d = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        for chave in ("cobertura", "avaliados", "picos"):
            self.d.setdefault(chave, [])
        self.d.setdefault("inicio", None)

    def salvar(self) -> None:
        with self._trava:
            temp = self.caminho.with_suffix(".tmp")
            try:
                self.caminho.parent.mkdir(parents=True, exist_ok=True)
                temp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
                temp.replace(self.caminho)
            except OSError:
                log.warning("Não consegui guardar o progresso da live em %s", self.caminho)

    def abrir_cobertura(self, t: float) -> None:
        with self._trava:
            self.d["cobertura"].append([t, t])
            if self.d["inicio"] is None:
                self.d["inicio"] = t

    def estender_cobertura(self, t: float) -> None:
        with self._trava:
            if self.d["cobertura"]:
                self.d["cobertura"][-1][1] = t

    def coberto(self, t: float) -> bool:
        return any(a - self.MARGEM_S <= t <= b + self.MARGEM_S for a, b in self.d["cobertura"])

    def marcar_avaliado(self, sq_a: int, sq_b: int) -> None:
        with self._trava:
            self.d["avaliados"].append([sq_a, sq_b])
        self.salvar()

    def avaliado(self, sq: int) -> bool:
        return any(a <= sq < b for a, b in self.d["avaliados"])


class AnalisePassado:
    """Segunda frente do acompanhamento: corta o que já tinha passado da live."""

    def __init__(self, monitor):
        self.m = monitor
        self.cfg = monitor.cfg
        self.pasta = monitor.pasta / "passado"
        self.cortes: list[int] = []
        self.estado = monitor.estado.setdefault("passado", {"etapa": "Preparando", "cortes": 0})
        self.progresso: Progresso = monitor.progresso

    def _etapa(self, texto: str) -> None:
        self.estado["etapa"] = texto

    def rodar(self) -> None:
        try:
            self._rodar()
        except Exception as e:  # noqa: BLE001 — a frente em tempo real continua de qualquer jeito
            log.exception("Falha ao analisar o que já passou da live")
            self._etapa(f"Não deu para olhar o que já passou: {e}")
        finally:
            # Os pedaços de áudio ficam até a live acabar (ou você parar): se o programa for
            # fechado, ao reabrir eles não são baixados de novo.
            (self.pasta / "audio.m4a").unlink(missing_ok=True)

    def _rodar(self) -> None:
        cfg, lv, parar = self.cfg, self.cfg["live"], self.m._parar
        self._etapa("Localizando o começo da live")
        fm = fonte_do_passado(self.m.url, lv["altura"])
        agora_sq = fm.cabeca()
        frag = fm.frag
        horas = float(lv.get("historico_horas", 6))
        primeiro = max(0, agora_sq - int(horas * 3600 / frag))
        if (agora_sq - primeiro) * frag < 180:
            self._etapa("A live começou há pouco: nada para olhar para trás")
            return
        agora_relogio = time.time()
        passado_s = (agora_sq - primeiro) * frag
        retomada = bool(self.progresso.d["avaliados"] or len(self.progresso.d["cobertura"]) > 1)
        log.info("Live %s: analisando também os %.0f min que já passaram%s.",
                 self.m.meta["id"], passado_s / 60, " (retomando)" if retomada else "")

        # 1. Só o áudio de todo o período, para achar os momentos.
        def prog(f):
            self._etapa(f"Baixando o áudio dos {passado_s / 60:.0f} min que já passaram "
                        f"({f * 100:.0f}%)")
        prog(0)
        pedacos_audio = baixar(fm, "a", primeiro, agora_sq, self.pasta / "a", "a", parar, prog)
        if parar.is_set() or not pedacos_audio:
            return
        self._etapa("Medindo a empolgação do que já passou")
        audio_total = juntar(pedacos_audio, self.pasta / "audio.m4a", fm, "a")
        volume = sinais.volume_por_segundo(audio_total)
        audio_total.unlink(missing_ok=True)
        if len(volume) < 60:
            self._etapa("Não consegui ouvir o que já passou")
            return
        pontuacao, _ = sinais.analisar(audio=volume, mensagens=None, replay=None,
                                       duracao=len(volume), cfg=cfg)
        # O áudio emendado começa no pedaço `primeiro`, mas pedaços perdidos encurtam a
        # série: usa a posição real de cada pedaço para voltar ao número "sq".
        seq_audio = [int(p.stem.split("_")[1]) for p in pedacos_audio]
        pontuacao = self._sem_o_que_ja_foi_visto(pontuacao, seq_audio, frag, agora_sq,
                                                 agora_relogio)
        duracao = cfg["cortes"]["duracao"]
        meta_cortes = cfg["cortes"]["por_video"]
        janelas = sinais.melhores_janelas(pontuacao, duracao, meta_cortes * 2,
                                          cfg["cortes"]["intervalo_minimo"])

        # 2. Os melhores momentos, um a um: vídeo só desses trechos, IA e renderização.
        self.m.meta["referencias"] = desempenho.referencias(self.m.banco)
        for n, (inicio, nota_sinal) in enumerate(janelas):
            if parar.is_set() or len(self.cortes) >= meta_cortes:
                break
            self._etapa(f"Avaliando momento {n + 1} de {len(janelas)} do que já passou "
                        f"({len(self.cortes)} cortes)")
            try:
                self._candidato(fm, seq_audio, pontuacao, inicio, nota_sinal, primeiro)
            except Exception:  # noqa: BLE001 — um trecho ruim não derruba os outros
                log.exception("Falha num trecho do que já passou da live")
        self._etapa(f"Pronto: {len(self.cortes)} cortes do que já passou"
                    if not parar.is_set() else "Interrompido")

    def _sem_o_que_ja_foi_visto(self, pontuacao, seq_audio: list[int], frag: float,
                                agora_sq: int, agora_relogio: float):
        """Zera na pontuação o que a frente em tempo real já acompanhou e o que já foi
        avaliado antes de o programa fechar: a busca cai só no que ninguém viu."""
        pontuacao = np.array(pontuacao, dtype=np.float32)
        ignorados = 0
        for i in range(len(pontuacao)):
            sq = seq_audio[min(int(i // frag), len(seq_audio) - 1)]
            relogio = agora_relogio - (agora_sq - sq) * frag
            if self.progresso.avaliado(sq) or self.progresso.coberto(relogio):
                pontuacao[i] = 0
                ignorados += 1
        if ignorados:
            log.info("Live %s: %.0f min já vistos ficam de fora da busca no passado.",
                     self.m.meta["id"], ignorados / 60)
        return pontuacao

    def _candidato(self, fm, seq_audio: list[int], pontuacao, inicio: int,
                   nota_sinal: float, primeiro: int) -> None:
        cfg, frag = self.cfg, fm.frag
        duracao = cfg["cortes"]["duracao"]
        ini, fim = sinais.ajustar_ao_pico(pontuacao, inicio, duracao)
        antes, depois = 9, 16 + min(15, int(cfg["cortes"].get("extensao_max", 40)))
        # segundo da série -> pedaço "sq" (a série é a emenda dos pedaços baixados)
        i_a = max(0, int((ini - antes) // frag))
        i_b = min(len(seq_audio), int(math.ceil((fim + depois) / frag)))
        if i_b <= i_a:
            return
        sq_a, sq_b = seq_audio[i_a], seq_audio[i_b - 1] + 1
        self.progresso.marcar_avaliado(sq_a, sq_b)
        base = i_a * frag  # segundo da série em que o trecho começa
        pasta = self.pasta / f"t{sq_a}"
        try:
            # Todos os pedaços, de vídeo e de áudio: um pedaço de 5 s faltando no meio faz a
            # imagem pular para a frente e o som ficar atrás (corte dessincronizado). Os que
            # falharem são baixados de novo; se ainda faltar algum, o trecho é pulado.
            precisa = sq_b - sq_a
            videos: list[Path] = []
            audios: list[Path] = []
            for _ in range(2):
                videos = baixar(fm, "v", sq_a, sq_b, pasta, "v", self.m._parar)
                if fm.video_com_audio:  # Twitch: o vídeo já traz o som
                    audios = videos
                else:
                    audios = baixar(fm, "a", sq_a, sq_b, self.pasta / "a", "a", self.m._parar)
                if len(videos) == precisa and len(audios) == precisa:
                    break
            if len(videos) != precisa or len(audios) != precisa:
                log.info("Trecho %d–%d do passado incompleto (vídeo %d, áudio %d de %d); pulado.",
                         sq_a, sq_b, len(videos), len(audios), precisa)
                return
            trecho = pasta / "trecho.mp4"
            if fm.video_com_audio:
                entradas = ["-i", str(juntar(videos, pasta / "v.mp4", fm, "v")),
                            "-map", "0:v:0", "-map", "0:a:0"]
            else:
                entradas = ["-i", str(juntar(videos, pasta / "v.mp4", fm, "v")),
                            "-i", str(juntar(audios, pasta / "a.mp4", fm, "a")),
                            "-map", "0:v:0", "-map", "1:a:0"]
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", *entradas, "-c", "copy",
                 "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(trecho)],
                check=True, timeout=300)
            dif = diferenca_faixas(trecho)
            if dif > 0.5:
                log.warning("Trecho %d–%d do passado com vídeo e áudio desencontrados (%.1f s); "
                            "pulado.", sq_a, sq_b, dif)
                return
            dur_arq = fontes.duracao_arquivo(trecho)
            falas = transcricao.transcrever(trecho, 0, dur_arq, cfg["idioma"],
                                            cfg["transcricao"]["whisper"])
            ini_arq, fim_arq = max(0.0, ini - base), min(dur_arq, fim - base)
            ini_arq, fim_arq = transcricao.ajustar_bordas(falas, ini_arq, fim_arq)
            # Tempo do corte = segundos desde o início da live (o pedaço 0).
            t0 = sq_a * frag
            c = {
                "inicio": t0 + ini_arq, "fim": t0 + fim_arq,
                "inicio_arquivo": ini_arq, "fim_arquivo": fim_arq,
                "pontuacao": nota_sinal, "falas": falas,
                "folga_inicio": min(8, ini_arq), "folga_fim": max(0, min(15, dur_arq - fim_arq)),
                "transcricao": vod._marcada(falas, ini_arq, fim_arq), "chat": [],
            }
            avaliado = ia.avaliar([c], self.m.meta, trecho, cfg)
            c = avaliado[0] if avaliado else None
            motivo = ia.motivo_descarte(c, cfg["ia"]["nota_minima"])
            if motivo:
                log.info("Momento do passado descartado: %s", motivo)
                return
            corte = vod.finalizar(c, trecho, self.m.meta, cfg, self.m.banco, self.m.pasta, "live",
                                  falas)
            self.cortes.append(corte)
            self.m.cortes.append(corte)
            self.estado["cortes"] = len(self.cortes)
            publicar.publicar_pendentes(cfg, self.m.banco)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
