"""Painel web: acompanha lives, análises, cortes e publicações num só lugar.

Servidor local simples (biblioteca padrão). O Gerenciador roda as tarefas em segundo
plano; a página consulta /api/estado a cada 2 segundos.
"""
from __future__ import annotations

import html
import os
import itertools
import json
import logging
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import (ajustes, conhecimento,  # noqa: I001
               seguranca, desempenho, enquadramento, fontes, ia, narracao,
               publicar, transcricao, vod)
from .banco import MAX_TENTATIVAS, PLATAFORMAS, SO_CURTOS, Banco
from .publicar import tiktok
from .live import MonitorLive

log = logging.getLogger(__name__)
PAGINA = Path(__file__).with_name("painel.html")


class Gerenciador:
    def __init__(self, cfg: dict, banco: Banco, caminho_cfg: str = "config.yaml",
                 porta: int = 8000):
        self.cfg, self.banco = cfg, banco
        self.caminho_cfg, self.porta = caminho_cfg, porta
        self._fluxo_youtube = None
        self._estado_youtube = ""
        self._estado_tiktok = ""
        self._verificador_tiktok: str | None = None
        self.senha = ""                      # definida só quando o painel é aberto à rede
        self.hosts_aceitos: set[str] = set()
        self._canal_yt: tuple[float, dict | None] = (0.0, None)
        self.tarefas: dict[str, dict] = {}
        self.refazendo: dict[int, dict] = {}  # cortes sendo refeitos com outro começo/fim
        self.trechos: dict[str, dict] = {}    # "video:posição" de trechos da análise sendo cortados
        self.lives: dict[str, MonitorLive] = {}
        self._trava = threading.RLock()
        self._fila = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analise")
        self._seq = itertools.count(1)
        self._ultima_busca = 0.0
        self._ultima_medida = 0.0
        self._retomar()
        threading.Thread(target=self._laco, daemon=True, name="painel-laco").start()

    # --- retomada: o que estava rodando quando o programa fechou volta ao abrir ---
    def _em_andamento(self) -> list[dict]:
        with self._trava:
            lives = [{"alvo": m.url, "teste": bool(m.meta.get("teste"))}
                     for m in self.lives.values()
                     if m.estado["status"] in {"conectando", "acompanhando"} and not m.parado_pelo_usuario]
            tarefas = [{"alvo": t["alvo"], "teste": t["teste"]} for t in self.tarefas.values()
                       if t["status"] in {"identificando", "fila", "rodando", "pausado", "agendada"}
                       and not t.get("cancelar")]
        return [x for x in lives + tarefas if re.match(r"https?://", x["alvo"])]

    def _guardar(self) -> None:
        if getattr(self, "_encerrado", False):  # a lista final já foi gravada ao fechar
            return
        self.banco.definir_opcao("em_andamento", json.dumps(self._em_andamento()))

    def _retomar(self) -> None:
        try:
            pendentes = json.loads(self.banco.opcao("em_andamento", "[]"))
        except json.JSONDecodeError:
            pendentes = []
        for p in pendentes:
            log.info("Retomando %s", p["alvo"])
            self.enviar(p["alvo"], p["teste"], origem="retomado")

    def _tentar_retomar_de_novo(self, tarefa: dict, como_live: bool, erro: Exception) -> bool:
        """Na abertura do programa a rede e o yt-dlp às vezes ainda não estão prontos: uma
        análise ou live retomada que falha ao ser identificada tenta de novo (3 vezes, com
        espera crescente) em vez de sumir com erro."""
        n = tarefa.get("tentativas_retomada", 0) + 1
        if tarefa.get("origem") != "retomado" or n > 3 or tarefa.get("cancelar"):
            return False
        tarefa.update(tentativas_retomada=n, etapa=f"Tentando de novo ({n} de 3)…")
        log.warning("Retomada de %s falhou (%s); tentando de novo (%d de 3).",
                    tarefa["alvo"], _resumo(erro), n)
        threading.Timer(15 * n, self._identificar, args=(tarefa, como_live)).start()
        return True

    def ativos(self) -> int:
        return len(self._em_andamento())

    def encerrar(self) -> None:
        """Fecha com ordem: guarda o que estava em andamento (para retomar ao abrir de novo),
        para as capturas e interrompe as análises, para o programa não seguir trabalhando
        escondido depois que a janela fecha."""
        self._guardar()
        self._encerrado = True
        with self._trava:
            monitores = list(self.lives.values())
            for t in self.tarefas.values():
                if t["status"] in {"identificando", "fila", "rodando", "pausado", "agendada"}:
                    t["cancelar"] = True
        for m in monitores:
            m.parar()

    # --- entrada de links ---
    def enviar(self, alvo: str, teste: bool, como_live: bool = False, origem: str = "manual",
               permitir_arquivo: bool = True) -> dict:
        alvo = str(alvo).strip()
        if not alvo:
            raise ValueError("Informe um link do YouTube.")
        if re.match(r"https?://", alvo, re.I):
            alvo = seguranca.validar_link(alvo)
        elif permitir_arquivo:
            alvo = seguranca.validar_arquivo(alvo)
        else:  # quem acessa de outro aparelho não pode apontar para arquivos deste computador
            raise ValueError("Arquivos locais só podem ser enviados no próprio computador.")
        tarefa = {
            "id": f"t{next(self._seq)}", "alvo": alvo, "titulo": alvo, "canal": "", "teste": teste,
            "origem": origem, "status": "identificando", "etapa": "Identificando o vídeo",
            "fracao": None, "erro": "", "video_id": "", "cortes": 0, "inicio": time.time(),
            "fim": None, "como_live": como_live,
        }
        with self._trava:
            self.tarefas[tarefa["id"]] = tarefa
        threading.Thread(target=self._identificar, args=(tarefa, como_live), daemon=True).start()
        return tarefa

    def _identificar(self, tarefa: dict, como_live: bool) -> None:
        try:
            meta = fontes.info(tarefa["alvo"])
            meta["teste"] = tarefa["teste"]
            # Link enviado por você = canal confiável para cortes.
            self.banco.canal_confiavel(meta["canal_id"], meta["canal"])
            if meta.get("agendada") is not None:  # live que ainda vai começar: espera por ela
                tarefa.update(titulo=meta["titulo"], canal=meta["canal"], video_id=meta["id"],
                              status="agendada", inicio_live=meta["agendada"] or None,
                              etapa="Aguardando a live começar")
                self._esperar_live(tarefa)
                return
            if meta["ao_vivo"] or como_live:
                entrada = (["-re", "-i", meta["arquivo"], "-c", "copy"] if "arquivo" in meta else None)
                self._iniciar_live(tarefa["alvo"], meta, entrada)
                with self._trava:
                    del self.tarefas[tarefa["id"]]
                return
            tarefa.update(titulo=meta["titulo"], canal=meta["canal"], video_id=meta["id"])
            limite_h = float(self.cfg["fontes"].get("duracao_max_h", 6) or 0)
            if tarefa["origem"] == "manual" and limite_h and meta["duracao"] > limite_h * 3600:
                # Antes o vídeo era ignorado em silêncio e o cartão dizia "Concluído".
                raise ValueError(
                    f"Vídeo de {meta['duracao'] / 3600:.1f} h: passa do limite de {limite_h:g} h. "
                    "Aumente “Vídeo mais longo aceito” em Configurações → Cortes e tente de novo.")
            # Um vídeo já cortado e publicado não é cortado de novo: evita posts repetidos.
            if not tarefa["teste"] and self.banco.status_video(meta["id"]) == "feito" \
                    and self.banco.tem_publicados(meta["id"]):
                if tarefa["origem"] != "manual":
                    with self._trava:
                        del self.tarefas[tarefa["id"]]
                    return
                raise ValueError("Este vídeo já foi cortado. Para refazer sem publicar de "
                                 "novo, envie em modo teste.")
            tarefa.update(status="fila", etapa="Na fila")
            self._fila.submit(self._analisar, tarefa, meta)
        except Exception as e:  # noqa: BLE001
            if self._tentar_retomar_de_novo(tarefa, como_live, e):
                return
            log.exception("Falha ao identificar %s", tarefa["alvo"])
            tarefa.update(status="erro", erro=_resumo(e), fim=time.time())

    def _esperar_live(self, tarefa: dict, verificar_a_cada: float = 60.0, desistir_apos_h: float = 6.0) -> None:
        """Live agendada: dorme até perto da hora marcada e então confere a cada minuto. Quando
        ela entra no ar, começa a acompanhar sozinha. Cancelável pelo botão da tarefa."""
        limite = (tarefa.get("inicio_live") or time.time()) + desistir_apos_h * 3600
        while True:
            if tarefa.get("cancelar"):
                tarefa.update(status="cancelado", etapa="Cancelada", fim=time.time())
                return
            agora, marcada = time.time(), tarefa.get("inicio_live")
            if marcada and marcada - agora > verificar_a_cada * 2:
                # Ainda longe: só confere de novo perto da hora (acordando a cada segundo para
                # o botão Cancelar responder na hora).
                tarefa["etapa"] = "Aguardando a live começar"
                time.sleep(1)
                continue
            try:
                meta = fontes.info(tarefa["alvo"])
            except Exception as e:  # noqa: BLE001 — rede caiu: tenta de novo no próximo minuto
                log.warning("Live agendada %s: falha ao conferir (%s)", tarefa["alvo"], _resumo(e))
                meta = None
            if meta and meta.get("ao_vivo"):
                meta["teste"] = tarefa["teste"]
                log.info("A live %s começou: acompanhando.", meta["id"])
                self._iniciar_live(tarefa["alvo"], meta, None)
                with self._trava:
                    self.tarefas.pop(tarefa["id"], None)
                return
            if meta and meta.get("agendada") is None:  # não é mais live (virou vídeo): analisa
                meta["teste"] = tarefa["teste"]
                tarefa.update(status="fila", etapa="Na fila")
                self._fila.submit(self._analisar, tarefa, meta)
                return
            if meta and meta.get("agendada"):
                tarefa["inicio_live"] = meta["agendada"]  # o canal pode ter mudado o horário
                limite = max(limite, meta["agendada"] + desistir_apos_h * 3600)
            if time.time() > limite:
                tarefa.update(status="erro", erro="A live não começou até 6 h depois do horário marcado.",
                              fim=time.time())
                return
            tarefa["etapa"] = "Conferindo se a live já começou"
            for _ in range(int(verificar_a_cada)):
                if tarefa.get("cancelar"):
                    break
                time.sleep(1)

    @staticmethod
    def _ponto_de_parada(tarefa: dict) -> None:
        """Chamado entre as etapas da análise: segura enquanto estiver pausada e interrompe se
        for cancelada. O passo em curso (um download, um corte sendo renderizado) termina antes."""
        if tarefa.get("pausar") and not tarefa.get("cancelar"):
            tarefa["status"] = "pausado"
            while tarefa.get("pausar") and not tarefa.get("cancelar"):
                time.sleep(0.5)
            tarefa["status"] = "rodando"
        if tarefa.get("cancelar"):
            raise vod.Cancelado()

    def _analisar(self, tarefa: dict, meta: dict) -> None:
        def progresso(etapa: str, fracao: float | None = None) -> None:
            tarefa.update(etapa=etapa, fracao=fracao, mudou=time.time(), vigiado=False)
            self._ponto_de_parada(tarefa)

        # A thread e a hora da última etapa deixam o vigia (em _laco) apontar no log onde uma
        # análise parada há muito tempo está presa.
        tarefa.update(status="rodando", inicio=time.time(), mudou=time.time(), vigiado=False,
                      thread=threading.get_ident())
        try:
            self._ponto_de_parada(tarefa)  # cancelada ainda na fila: nem começa
            # Os cortes já feitos deste vídeo ficam (antes um novo teste apagava os anteriores,
            # e reabrir o programa, que retoma as análises, fazia perder cortes). A análise
            # pula os trechos que já viraram corte, então nada se repete.
            ids = vod.processar(tarefa["alvo"], self.cfg, self.banco, forcar=True, meta=meta,
                                progresso=progresso)
            tarefa.update(status="feito", etapa="Concluído", fracao=1.0, cortes=len(ids),
                          fim=time.time())
        except Exception as e:  # noqa: BLE001
            # O yt-dlp embrulha o cancelamento feito durante o download num erro próprio:
            # qualquer falha depois do clique em Cancelar conta como cancelamento.
            if isinstance(e, vod.Cancelado) or tarefa.get("cancelar"):
                # Os cortes já renderizados continuam na aba Cortes; o vídeo fica "parcial",
                # então pode ser enviado de novo (e os trechos já cortados não se repetem).
                prontos = len([c for c in self.banco.cortes_do_video(meta["id"])
                               if c["criado"] >= tarefa["inicio"]])
                self.banco.marcar_video(meta["id"], meta["titulo"], meta["canal"], "parcial")
                tarefa.update(status="cancelado", etapa="Cancelada", cortes=prontos,
                              fim=time.time())
                log.info("Análise de %s cancelada com %d corte(s) pronto(s).", meta["id"], prontos)
                return
            log.exception("Falha ao analisar %s", tarefa["alvo"])
            self.banco.marcar_video(meta["id"], meta["titulo"], meta["canal"], "erro")
            tarefa.update(status="erro", erro=_resumo(e), fim=time.time())
        except BaseException as e:  # noqa: BLE001
            # O ThreadPoolExecutor engole o que não é Exception sem registrar nada, e a tarefa
            # ficaria "Analisando" para sempre: registra e marca como erro.
            log.exception("Análise de %s interrompida", tarefa["alvo"])
            tarefa.update(status="erro", erro=f"Análise interrompida ({type(e).__name__}).",
                          fim=time.time())
            raise

    # --- lives ---
    def _iniciar_live(self, alvo: str, meta: dict, entrada: list[str] | None) -> None:
        with self._trava:
            atual = self.lives.get(meta["id"])
            if atual and atual.estado["status"] in {"conectando", "acompanhando"}:
                raise ValueError("Esta live já está sendo acompanhada.")
            monitor = MonitorLive(alvo, self.cfg, self.banco, meta=meta, entrada_ffmpeg=entrada)
            self.lives[meta["id"]] = monitor

        def rodar() -> None:
            try:
                monitor.rodar()
            except Exception as e:  # noqa: BLE001
                log.exception("Live %s falhou", meta["id"])
                monitor.estado.update(status="erro", erro=_resumo(e))

        threading.Thread(target=rodar, daemon=True, name=f"live-{meta['id']}").start()

    def parar_live(self, live_id: str) -> None:
        self.lives[live_id].parado_pelo_usuario = True
        self.lives[live_id].parar()

    def fechar_live(self, live_id: str) -> None:
        with self._trava:
            if self.lives[live_id].estado["status"] in {"encerrada", "erro"}:
                del self.lives[live_id]

    def tentar_de_novo(self, tarefa_id: str | None = None, permitir_arquivo: bool = True) -> int:
        """Reenvia a análise que deu erro (ou, sem id, todas as que deram erro) com o mesmo
        link e as mesmas opções (modo teste, como live, origem). O cartão do erro some e
        entra um novo. Devolve quantas foram reenviadas."""
        with self._trava:
            if tarefa_id is not None:
                t = self.tarefas.get(tarefa_id)
                if not t or t["status"] != "erro":
                    raise ValueError("Esta análise não está mais com erro.")
                falhas = [t]
            else:
                falhas = sorted((t for t in self.tarefas.values() if t["status"] == "erro"),
                                key=lambda t: t["inicio"])
            for t in falhas:
                del self.tarefas[t["id"]]
        for t in falhas:
            self.enviar(t["alvo"], t["teste"], t.get("como_live", False), t.get("origem", "manual"),
                        permitir_arquivo=permitir_arquivo)
        return len(falhas)

    def fechar_tarefa(self, tarefa_id: str) -> None:
        with self._trava:
            if self.tarefas[tarefa_id]["status"] in {"feito", "erro", "cancelado"}:
                del self.tarefas[tarefa_id]

    def refazer_corte(self, corte_id: int, ajuste_inicio, ajuste_fim) -> None:
        """Começa a refazer um corte em segundo plano (o painel acompanha em `refazendo`)."""
        try:
            ai = float(str(ajuste_inicio or 0).replace(",", "."))
            af = float(str(ajuste_fim or 0).replace(",", "."))
        except ValueError:
            raise ValueError("Use números de segundos, como -5 ou 10.") from None
        if not ai and not af:
            raise ValueError("Mude o início ou o fim antes de refazer.")
        if abs(ai) > 120 or abs(af) > 120:
            raise ValueError("Ajuste de no máximo 120 segundos por vez.")
        with self._trava:
            atual = self.refazendo.get(corte_id)
            if atual and atual["status"] == "rodando":
                raise ValueError("Este corte já está sendo refeito.")
            estado = {"status": "rodando", "etapa": "Começando", "erro": ""}
            self.refazendo[corte_id] = estado

        def rodar() -> None:
            try:
                vod.refazer(corte_id, ai, af, self.cfg, self.banco,
                            progresso=lambda etapa: estado.update(etapa=etapa))
                estado.update(status="feito", etapa="Pronto")
            except Exception as e:  # noqa: BLE001
                log.exception("Falha ao refazer o corte %s", corte_id)
                estado.update(status="erro", erro=_resumo(e))

        threading.Thread(target=rodar, daemon=True, name=f"refazer-{corte_id}").start()

    def cortar_trecho(self, video_id: str, posicao: int) -> None:
        """Gera, em segundo plano, o corte de um trecho da análise que ficou de fora."""
        if posicao < 0:
            raise ValueError("Trecho inválido.")
        chave = f"{video_id}:{posicao}"
        with self._trava:
            atual = self.trechos.get(chave)
            if atual and atual["status"] == "rodando":
                raise ValueError("Este trecho já está sendo cortado.")
            estado = {"status": "rodando", "etapa": "Começando", "erro": "", "corte": None}
            self.trechos[chave] = estado

        def rodar() -> None:
            try:
                corte = vod.cortar_candidato(video_id, posicao, self.cfg, self.banco,
                                             progresso=lambda etapa: estado.update(etapa=etapa))
                estado.update(status="feito", etapa="Pronto", corte=corte)
            except Exception as e:  # noqa: BLE001
                log.exception("Falha ao cortar o trecho %s", chave)
                estado.update(status="erro", erro=_resumo(e))

        threading.Thread(target=rodar, daemon=True, name=f"trecho-{chave}").start()

    def decidir_corte(self, corte_id: int, modo: str, plataformas=PLATAFORMAS) -> str:
        """Sua decisão sobre um corte, nas plataformas escolhidas: "agora" publica já;
        "fila" coloca na fila de postagem (respeitando intervalo, horários e limite diário)."""
        if modo not in {"agora", "fila"}:
            raise ValueError("Escolha publicar agora ou colocar na fila.")
        corte = self.banco.corte(corte_id)
        if not corte:
            raise ValueError("Corte não encontrado.")
        if not Path(corte["arquivo"]).exists():
            raise ValueError("O arquivo deste corte não existe mais.")
        destinos = [p for p in plataformas
                    if not corte[f"{p}_id"] and self.cfg["publicar"][publicar.NOMES[p]]["ativo"]
                    and not (p in SO_CURTOS and corte["origem"] == "compilacao")]
        if not destinos:
            raise ValueError("Este corte já foi publicado nas plataformas escolhidas (ou elas "
                             "estão desligadas nas Configurações).")
        nomes = _juntar([publicar.ROTULOS[p] for p in destinos])
        if modo == "fila":
            self.banco.aprovar(corte_id, destinos)
            return f"Corte colocado na fila do {nomes}."
        conectados = [p for p in destinos if publicar.conectado(p, self.cfg)]
        if not conectados:
            raise ValueError("Nenhuma conta conectada para publicar agora (veja Configurações).")
        self.banco.aprovar(corte_id, conectados)
        for p in conectados:
            if publicar.enviando(corte_id, p):
                continue
            self.banco.tentar_de_novo(corte_id, p)
            threading.Thread(target=publicar.publicar_um, daemon=True,
                             args=(self.cfg, self.banco, self.banco.corte(corte_id), p)).start()
        nomes = _juntar([publicar.ROTULOS[p] for p in conectados])
        return f"Publicando agora no {nomes}. Acompanhe o andamento na aba Publicações."

    def controlar_tarefa(self, tarefa_id: str, comando: str) -> None:
        tarefa = self.tarefas.get(tarefa_id)
        if not tarefa or tarefa["status"] not in {"identificando", "fila", "rodando", "pausado", "agendada"}:
            raise ValueError("Esta análise já terminou.")
        if tarefa["status"] == "agendada" and comando != "cancelar":
            raise ValueError("Uma live agendada só pode ser cancelada.")
        if comando == "pausar":
            tarefa["pausar"] = True
            if tarefa["status"] == "rodando":
                tarefa["etapa"] = f"Pausando ao fim da etapa atual ({tarefa['etapa']})"
        elif comando == "retomar":
            tarefa["pausar"] = False
        elif comando == "cancelar":
            tarefa["cancelar"] = True
            if tarefa["status"] in {"rodando", "pausado"}:
                tarefa["etapa"] = "Cancelando ao fim da etapa atual…"

    # --- segundo plano: publicação e canais seguidos ---
    def _laco(self) -> None:
        while True:
            time.sleep(30)
            try:
                self._guardar()
                self._vigiar()
                publicar.publicar_pendentes(self.cfg, self.banco)
                if time.time() - self._ultima_medida >= 3600:
                    self._ultima_medida = time.time()
                    desempenho.atualizar(self.cfg, self.banco)
                    ativas = [p for p, nome in publicar.NOMES.items()
                              if self.cfg["publicar"][nome]["ativo"]]
                    apagados = self.banco.limpar_antigos(self.cfg["limpeza"]["dias"], ativas)
                    if apagados:
                        log.info("Limpeza: %d cortes antigos apagados do disco.", apagados)
                if time.time() - self._ultima_busca >= self.cfg["auto"]["intervalo_min"] * 60:
                    self._ultima_busca = time.time()
                    self._buscar_nos_canais()
            except Exception:  # noqa: BLE001
                log.exception("Erro no ciclo de segundo plano")

    def _vigiar(self, parada_s: float = 600) -> None:
        """Análise sem mudar de etapa há mais de 10 min: grava no log onde ela está presa
        (uma vez por etapa), para o problema poder ser achado sem adivinhação."""
        import sys
        import traceback

        quadros = sys._current_frames()
        with self._trava:
            presas = [t for t in self.tarefas.values() if t["status"] == "rodando"
                      and not t.get("vigiado") and time.time() - t.get("mudou", time.time()) > parada_s]
        for t in presas:
            t["vigiado"] = True
            quadro = quadros.get(t.get("thread"))
            # A thread já pegou outra análise da fila: esta terminou sem avisar.
            reaproveitada = any(o is not t and o.get("thread") == t.get("thread")
                                and o.get("inicio", 0) > t.get("inicio", 0)
                                and o["status"] in {"rodando", "pausado"} for o in self.tarefas.values())
            if quadro is None or reaproveitada:  # a análise morreu sem avisar
                log.error("Análise de %s sumiu na etapa '%s'.", t["alvo"], t.get("etapa"))
                t.update(status="erro", erro="A análise parou sem avisar. Envie o link de novo.",
                         fim=time.time())
                continue
            log.warning("Análise de %s parada há %d min em '%s'. Onde está:\n%s", t["alvo"],
                        (time.time() - t["mudou"]) // 60, t.get("etapa"),
                        "".join(traceback.format_stack(quadro)[-12:]))

    def _buscar_nos_canais(self) -> None:
        seguidos = [c["id"] for c in self.banco.canais() if c["seguir"]]
        for canal in seguidos:
            try:
                achados = fontes._do_canal(canal, self.cfg["fontes"]["busca"]["max_resultados"])
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao listar canal %s: %s", canal, e)
                continue
            for a in achados:
                with self._trava:
                    ativas = sum(m.estado["status"] in {"conectando", "acompanhando"}
                                 for m in self.lives.values())
                    em_andamento = a["id"] in self.lives or any(
                        t["video_id"] == a["id"] or t["alvo"] == a["url"]
                        for t in self.tarefas.values())
                if em_andamento or self.banco.status_video(a["id"]) not in (None, "teste"):
                    continue
                if a["ao_vivo"] and ativas >= self.cfg["live"]["max_simultaneas"]:
                    continue
                self.enviar(a["url"], teste=False, origem="canal seguido")

    def _analises_anteriores(self, em_tela: set) -> list[dict]:
        """Vídeos já analisados (inclusive os que não renderam corte), para reabrir a análise
        e cortar à mão um trecho que ficou de fora."""
        pasta = Path(self.cfg["pasta_trabalho"])
        itens = []
        for v in self.banco._linhas("SELECT * FROM videos ORDER BY criado DESC LIMIT 60"):
            if v["id"] in em_tela or not (pasta / v["id"] / "analise.json").exists():
                continue
            itens.append({"id": f"h:{v['id']}", "anterior": True, "video_id": v["id"],
                          "titulo": v["titulo"] or v["id"], "canal": v["canal"] or "",
                          "status": v["status"], "criado": v["criado"]})
            if len(itens) >= 30:
                break
        return itens

    # --- retrato para a página ---
    def estado(self) -> dict:
        with self._trava:
            lives = [{
                "id": vid, "titulo": m.meta["titulo"], "canal": m.meta.get("canal", ""),
                "url": m.meta.get("url", ""), "teste": bool(m.meta.get("teste")),
                "cortes": len(m.cortes),
                **{**m.estado, "historico": list(m.estado["historico"]),
                   "picos": list(m.estado["picos"])[-8:]},
            } for vid, m in self.lives.items()]
            tarefas = sorted(self.tarefas.values(), key=lambda t: t["inicio"], reverse=True)
            tarefas = [dict(t) for t in tarefas]

        grupos: dict[str, dict] = {}
        fila = []
        previsto = publicar.previsao(self.cfg, self.banco)
        for c in self.banco.todos_cortes():
            item = {
                "id": c["id"], "titulo": c["titulo"], "descricao": c["descricao"],
                "hashtags": json.loads(c["hashtags"] or "[]"), "nota": c["nota"],
                "inicio": c["inicio"], "fim": c["fim"], "origem": c["origem"],
                "teste": bool(c["teste"]), "criado": c["criado"],
                "existe": Path(c["arquivo"]).exists(), "gancho": c["gancho"] or "",
                "notas": json.loads(c["notas"] or "{}"), "layout": c["layout"] or "",
                "narracao": c["narracao"] or "",
                "capa": bool(c["capa"] and Path(c["capa"]).exists()),
                "versao": Path(c["arquivo"]).name,  # muda ao refazer: o navegador recarrega o vídeo
                "ajustavel": vod.pode_refazer(c),
                "refazendo": self.refazendo.get(c["id"]),
                # plataformas em que o corte espera você decidir (fora da fila)
                "aguardando": [] if c["teste"] else [p for p in PLATAFORMAS
                                                     if c[f"{p}_aguardando"] and not c[f"{p}_id"]],
            }
            for p in PLATAFORMAS:
                if c[f"{p}_id"]:
                    situacao = "publicado"
                elif c["teste"]:
                    situacao = "teste"
                elif p in SO_CURTOS and c["origem"] == "compilacao":
                    situacao = "não se aplica"
                elif c[f"{p}_aguardando"]:
                    situacao = "aguardando"  # fora da fila até você decidir
                elif c[f"{p}_tentativas"] >= MAX_TENTATIVAS:
                    situacao = "falhou"
                else:
                    situacao = "na fila"
                envio = publicar.ENVIANDO.get((c["id"], p))
                if envio and situacao != "publicado":
                    situacao = "enviando"
                item[p] = {"situacao": situacao, "link": c[f"{p}_link"] or "",
                           "erro": c[f"{p}_erro"] or "", "quando": c[f"{p}_em"],
                           "tentativas": c[f"{p}_tentativas"], "vistas": c[f"{p}_vistas"],
                           "curtidas": c[f"{p}_curtidas"],
                           # andamento do envio e previsão de quando sai (fila automática)
                           "envio": dict(envio) if envio else None,
                           "previsto": previsto[p]["cortes"].get(c["id"])
                           if situacao == "na fila" else None}
            grupo = grupos.setdefault(c["video_id"], {
                "video_id": c["video_id"], "titulo": c["video_titulo"] or c["video_id"],
                "canal": c["canal"] or "", "origem": c["origem"], "cortes": []})
            grupo["cortes"].append(item)
            if not c["teste"]:
                fila.append({**item, "video": grupo["titulo"]})

        contas = {}
        for p, nome in publicar.NOMES.items():
            cfg_p = self.cfg["publicar"][nome]
            contas[p] = {
                "ativo": cfg_p["ativo"], "conectado": publicar.conectado(p, self.cfg),
                "hoje": self.banco.publicados_desde(p, time.time() - 86400),
                "max": cfg_p["max_por_dia"], "bloqueio": previsto[p]["bloqueio"],
            }
        return {
            "lives": lives, "tarefas": tarefas, "grupos": list(grupos.values()), "fila": fila,
            "trechos": {k: dict(v) for k, v in self.trechos.items()},
            "anteriores": self._analises_anteriores({t["video_id"] for t in tarefas}),
            "contas": contas, "canais": [dict(c) for c in self.banco.canais()],
            "publicacao_auto": self.banco.opcao("publicacao_auto", "1") == "1",
            "ia": ia.disponivel(self.cfg), "whisper": transcricao.whisper_disponivel(),
            "rostos": enquadramento.disponivel(),
            "aprendendo": bool(desempenho.referencias(self.banco)),
            "intervalo_min": self.cfg["publicar"]["intervalo_min"],
        }

    # --- monetização ---
    def monetizacao(self) -> dict:
        from .publicar import youtube

        agora = time.time()
        if agora - self._canal_yt[0] > 1800:  # consulta o canal no máximo a cada 30 min
            dados = None
            if publicar.conectado("yt", self.cfg):
                try:
                    dados = youtube.estatisticas(self.cfg["publicar"]["youtube"])
                except Exception as e:  # noqa: BLE001
                    log.warning("Não foi possível ler os números do canal: %s", _resumo(e))
            self._canal_yt = (agora, dados)
        vistas = self.banco.vistas_por_canal()
        campanhas = []
        for c in self.banco.canais():
            n = vistas.get(c["nome"], 0)
            campanhas.append({
                "id": c["id"], "nome": c["nome"] or c["id"], "valor_mil": c["valor_mil"] or 0,
                "vistas": n, "ganho": round(n / 1000 * (c["valor_mil"] or 0), 2),
                "tem_texto": bool(c["texto_obrigatorio"]), "tem_autorizacao": bool(c["autorizacao"])})
        return {
            "canal": self._canal_yt[1], "resumo": self.banco.resumo_monetizacao(),
            "campanhas": campanhas, "moeda": self.cfg["monetizacao"]["moeda"],
            "narracao": narracao.disponivel(self.cfg), "compilacao": self.cfg["compilacao"]["ativa"],
        }

    # --- configurações ---
    def ajustes(self) -> dict:
        cfg_yt = self.cfg["publicar"]["youtube"]
        definidas = ajustes.chaves_definidas()
        return {
            "secoes": ajustes.descrever(self.cfg),
            "chaves": [{"nome": n, "rotulo": r, "definida": definidas[n]}
                       for n, r in ajustes.CHAVES.items()],
            "youtube": {"tem_segredo": Path(cfg_yt["client_secret"]).exists(),
                        "conectado": publicar.conectado("yt", self.cfg)},
            "instagram": publicar.conectado("ig", self.cfg),
            "tiktok": {"tem_chaves": all(tiktok.chaves()),
                       "conectado": publicar.conectado("tt", self.cfg),
                       "retorno": self._retorno_tiktok()},
            "ia": ia.disponivel(self.cfg), "provedor": ia.provedor(self.cfg),
            "reserva": bool(ia.achar_claude_code()),
            "rostos": enquadramento.disponivel(),
            "whisper": transcricao.whisper_disponivel(),
            "voz": {"instalada": narracao.instalado(),
                    "arquivo": Path(self.cfg["narracao"]["voz"]).exists(),
                    **narracao.instalacao},
            "tem_cortes": bool(self.banco.todos_cortes()),
            "bases": [{"nome": b["nome"], "conteudo": b["bruto"], "sempre": b["sempre"],
                       "palavras": b["palavras"]} for b in conhecimento.listar(self.cfg)],
        }

    def youtube_iniciar(self) -> str:
        """Começa a autorização do canal e devolve o endereço da tela do Google."""
        import os

        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError:
            raise ValueError("Instale as dependências: pip install -r requirements.txt") from None
        from .publicar import youtube

        cfg_yt = self.cfg["publicar"]["youtube"]
        if not Path(cfg_yt["client_secret"]).exists():
            raise ValueError("Cole primeiro o conteúdo do client_secret.json (passo 2).")
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # o retorno é para este computador
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        self._fluxo_youtube = Flow.from_client_secrets_file(
            cfg_yt["client_secret"], youtube.ESCOPOS,
            redirect_uri=f"http://localhost:{self.porta}/oauth/youtube")
        url, self._estado_youtube = self._fluxo_youtube.authorization_url(
            access_type="offline", prompt="consent")
        return url

    def youtube_concluir(self, codigo: str, estado: str = "") -> None:
        if not self._fluxo_youtube:
            raise ValueError("A autorização expirou. Clique em Conectar de novo.")
        # O retorno precisa ser o da autorização que este painel iniciou; sem isso, um link
        # malicioso poderia conectar aqui o canal de outra pessoa.
        if not estado or not seguranca.senha_confere(estado, self._estado_youtube or ""):
            self._fluxo_youtube = None
            raise ValueError("Retorno de autorização inválido. Clique em Conectar de novo.")
        self._fluxo_youtube.fetch_token(code=codigo)
        Path(self.cfg["publicar"]["youtube"]["token"]).write_text(
            self._fluxo_youtube.credentials.to_json())
        self._fluxo_youtube = None

    def _retorno_tiktok(self) -> str:
        return f"http://localhost:{self.porta}/oauth/tiktok/"

    def tiktok_iniciar(self) -> str:
        url, self._estado_tiktok, self._verificador_tiktok = tiktok.iniciar_login(
            self._retorno_tiktok())
        return url

    def tiktok_concluir(self, codigo: str, estado: str = "") -> None:
        if not self._verificador_tiktok:
            raise ValueError("A autorização expirou. Clique em Conectar o TikTok de novo.")
        # Mesmo cuidado do YouTube: só aceita o retorno da autorização iniciada aqui.
        if not estado or not seguranca.senha_confere(estado, self._estado_tiktok or ""):
            self._verificador_tiktok = None
            raise ValueError("Retorno de autorização inválido. Clique em Conectar o TikTok de novo.")
        verificador, self._verificador_tiktok = self._verificador_tiktok, None
        tiktok.concluir_login(self.cfg["publicar"]["tiktok"], codigo, self._retorno_tiktok(),
                              verificador)

    # --- ações da página ---
    def acao(self, nome: str, d: dict, local: bool = True) -> dict:
        if not isinstance(d, dict):
            raise ValueError("Pedido inválido.")
        if nome == "ajustes/salvar":
            ajustes.salvar(self.cfg, d.get("valores") or {}, self.caminho_cfg)
            fontes.configurar(self.cfg)  # cookies valem na hora
        elif nome == "chave":
            ajustes.definir_chave(d.get("nome", ""), d.get("valor", ""))
            # Quem cola só a chave de um provedor quer usar esse provedor: troca sozinho.
            outro = {"NVIDIA_API_KEY": ("nvidia", "ANTHROPIC_API_KEY"),
                     "ANTHROPIC_API_KEY": ("anthropic", "NVIDIA_API_KEY")}.get(d.get("nome"))
            if outro and ia.provedor(self.cfg) != outro[0] and not os.environ.get(outro[1]):
                ajustes.salvar(self.cfg, {"ia.provedor": outro[0]}, self.caminho_cfg)
        elif nome == "ia/testar":
            return {"ok": True, "mensagem": ia.testar(self.cfg)}
        elif nome == "ia/testar_reserva":
            return {"ok": True, "mensagem": ia.testar_reserva(self.cfg)}
        elif nome == "youtube/segredo":
            try:
                dados = json.loads(d.get("conteudo") or "")
            except json.JSONDecodeError:
                raise ValueError("Isso não é o conteúdo de um client_secret.json.") from None
            if not isinstance(dados, dict) or not ({"installed", "web"} & set(dados)):
                raise ValueError("Use uma credencial OAuth do tipo “App para computador”.")
            destino = Path(self.cfg["publicar"]["youtube"]["client_secret"])
            destino.write_text(json.dumps(dados))
            destino.chmod(0o600)
        elif nome == "youtube/conectar":
            return {"ok": True, "url": self.youtube_iniciar()}
        elif nome == "tiktok/conectar":
            return {"ok": True, "url": self.tiktok_iniciar()}
        elif nome == "voz/instalar":
            if narracao.instalacao["estado"] != "rodando":
                narracao.instalacao.update(estado="rodando", mensagem="Começando…")
                threading.Thread(target=narracao.instalar_voz, args=(self.cfg,), daemon=True).start()
        elif nome == "base/salvar":
            conhecimento.salvar(self.cfg, d.get("nome", ""), d.get("conteudo", ""))
        elif nome == "base/remover":
            conhecimento.remover(self.cfg, d.get("nome", ""))
        elif nome == "enviar":
            self.enviar(d.get("alvo", ""), bool(d.get("teste")), bool(d.get("como_live")),
                        permitir_arquivo=local)
        elif nome == "live/parar":
            self.parar_live(d["id"])
        elif nome == "live/fechar":
            self.fechar_live(d["id"])
        elif nome == "tarefa/tentar_de_novo":
            self.tentar_de_novo(d["id"], permitir_arquivo=local)
        elif nome == "tarefa/tentar_todas":
            n = self.tentar_de_novo(None, permitir_arquivo=local)
            if not n:
                raise ValueError("Nenhuma análise com erro para tentar de novo.")
            return {"ok": True, "mensagem": f"{n} {'análise enviada' if n == 1 else 'análises enviadas'} de novo."}
        elif nome == "tarefa/fechar":
            self.fechar_tarefa(d["id"])
        elif nome in {"tarefa/pausar", "tarefa/retomar", "tarefa/cancelar"}:
            self.controlar_tarefa(d["id"], nome.split("/")[1])
        elif nome == "corte/refazer":
            self.refazer_corte(int(d["id"]), d.get("inicio", 0), d.get("fim", 0))
        elif nome == "trecho/cortar":
            self.cortar_trecho(str(d.get("video", "")), int(d.get("pos", -1)))
        elif nome == "corte/aprovar":
            self.banco.aprovar(int(d["id"]))
        elif nome == "corte/decidir":
            return {"ok": True, "mensagem": self.decidir_corte(
                int(d["id"]), str(d.get("modo", "")), _plataformas(d.get("plataformas")))}
        elif nome == "corte/tirar_da_fila":
            corte_id, plats = int(d["id"]), _plataformas(d.get("plataformas"))
            if any(publicar.enviando(corte_id, p) for p in plats):
                raise ValueError("Este corte está sendo enviado agora; espere terminar.")
            if not self.banco.tirar_da_fila(corte_id, plats):
                raise ValueError("Este corte não está na fila.")
        elif nome == "fila/esvaziar":
            n = self.banco.tirar_da_fila()
            return {"ok": True, "mensagem": f"{n} {'corte voltou' if n == 1 else 'cortes voltaram'} "
                                            "para “Aguardando você”. Nada foi apagado."}
        elif nome == "corte/remover":
            if not self.banco.remover_corte(int(d["id"])):
                raise ValueError("Cortes já publicados não podem ser removidos por aqui.")
        elif nome == "corte/publicar":
            corte = self.banco.corte(int(d["id"]))
            plataforma = d["plataforma"]
            if not corte or plataforma not in publicar.NOMES:
                raise ValueError("Corte ou plataforma inválidos.")
            if corte[f"{plataforma}_id"]:
                raise ValueError("Este corte já foi publicado nessa plataforma.")
            if not publicar.conectado(plataforma, self.cfg):
                raise ValueError(f"A conta do {publicar.NOMES[plataforma]} ainda não está conectada.")
            if corte["teste"]:
                raise ValueError("Aprove o corte de teste antes de publicar.")
            if publicar.enviando(corte["id"], plataforma):
                raise ValueError("Este corte já está sendo enviado. Acompanhe o andamento na fila.")
            self.banco.tentar_de_novo(corte["id"], plataforma)
            threading.Thread(target=publicar.publicar_um, daemon=True,
                             args=(self.cfg, self.banco, corte, plataforma)).start()
        elif nome == "canal/campanha":
            try:
                valor = float(str(d.get("valor_mil") or 0).replace(",", "."))
            except ValueError:
                raise ValueError("O valor por mil visualizações precisa ser um número.") from None
            self.banco.campanha(d["id"], max(0.0, valor), d.get("texto_obrigatorio", ""),
                                d.get("autorizacao", ""))
        elif nome == "canal/seguir":
            self.banco.seguir_canal(d["id"], bool(d["seguir"]))
            self._ultima_busca = 0.0
        elif nome == "canal/remover":
            self.banco.remover_canal(d["id"])
        elif nome == "publicacao_auto":
            self.banco.definir_opcao("publicacao_auto", "1" if d["ligada"] else "0")
        else:
            raise KeyError(nome)
        return {"ok": True}


def _plataformas(valor) -> tuple[str, ...]:
    """"yt", "ig", "tt", "yt,ig"... (ou lista) vindos da página; vazio = todas."""
    itens = valor if isinstance(valor, list) else str(valor or ",".join(PLATAFORMAS)).split(",")
    plats = tuple(p for p in PLATAFORMAS if p in {str(i).strip() for i in itens})
    if not plats:
        raise ValueError("Escolha pelo menos uma plataforma.")
    return plats


def _juntar(nomes: list[str]) -> str:
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _resumo(e: Exception) -> str:
    texto = re.sub(r"\x1b\[[0-9;]*m", "", seguranca.sem_segredos(e)).strip() or type(e).__name__
    return texto[:300]


def _manipulador(ger: Gerenciador):
    class Manipulador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # silencia o log por requisição
            pass

        def end_headers(self) -> None:
            for nome, valor in seguranca.CABECALHOS.items():
                self.send_header(nome, valor)
            super().end_headers()

        def _permitido(self) -> bool:
            """Barra pedidos que não vêm do próprio painel. Responde e devolve False se barrar."""
            # 1. O endereço pedido tem de ser o deste painel. Um site malicioso pode apontar
            #    o próprio domínio para 127.0.0.1 (DNS rebinding); o cabeçalho Host o denuncia.
            host = seguranca.host_do_pedido(self.headers.get("Host", ""))
            # Com senha (acesso pela rede), vale também o IP da máquina ou um nome autorizado.
            pela_rede = bool(ger.senha) and (seguranca.eh_ip(host) or host.lower() in ger.hosts_aceitos)
            if not (seguranca.host_local(host) or pela_rede):
                self._json({"erro": "Endereço não reconhecido."}, 403)
                return False
            # 2. Pedido vindo de outra página (outro site aberto no navegador) é recusado.
            origem = self.headers.get("Origin")
            if origem and origem != "null":
                partes = urlsplit(origem)
                if (partes.hostname or "") != host:
                    self._json({"erro": "Origem não permitida."}, 403)
                    return False
            # 3. Com senha definida (acesso por outros aparelhos), exige a senha.
            if ger.senha:
                import base64
                recebido = ""
                credencial = self.headers.get("Authorization", "")
                if credencial.startswith("Basic "):
                    try:
                        recebido = base64.b64decode(credencial[6:]).decode().partition(":")[2]
                    except (ValueError, UnicodeDecodeError):
                        recebido = ""
                if not seguranca.senha_confere(recebido, ger.senha):
                    time.sleep(0.5)  # atrasa tentativas em série
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="Cortes Virais"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return False
            return True

        def _json(self, dados, codigo: int = 200) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def _arquivo(self, caminho: Path, tipo: str) -> None:
            """Serve um arquivo com suporte a Range (necessário para o player de vídeo)."""
            if not caminho.exists():
                return self._json({"erro": "Arquivo não encontrado."}, 404)
            tamanho = caminho.stat().st_size
            ini, fim = 0, tamanho - 1
            faixa = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if faixa and (faixa[1] or faixa[2]):
                if faixa[1]:
                    ini = int(faixa[1])
                    fim = min(int(faixa[2]), fim) if faixa[2] else fim
                else:
                    ini = max(0, tamanho - int(faixa[2]))
                if ini > fim:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{tamanho}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {ini}-{fim}/{tamanho}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", tipo)
            if tipo.startswith("text/html"):  # a página muda com o programa: nunca usar cópia velha
                self.send_header("Cache-Control", "no-cache")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(fim - ini + 1))
            self.end_headers()
            with open(caminho, "rb") as f:
                f.seek(ini)
                resta = fim - ini + 1
                try:
                    while resta > 0:
                        bloco = f.read(min(256 * 1024, resta))
                        if not bloco:
                            break
                        self.wfile.write(bloco)
                        resta -= len(bloco)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # o navegador fechou a conexão ao pular no vídeo

        def do_GET(self) -> None:  # noqa: N802
            if not self._permitido():
                return
            rota = self.path.split("?")[0]
            if rota == "/":
                return self._arquivo(PAGINA, "text/html; charset=utf-8")
            if rota == "/api/estado":
                return self._json(ger.estado())
            if rota == "/api/monetizacao":
                return self._json(ger.monetizacao())
            if rota == "/api/ajustes":
                return self._json(ger.ajustes())
            if rota in ("/oauth/youtube", "/oauth/tiktok/", "/oauth/tiktok"):
                consulta = parse_qs(urlsplit(self.path).query)
                try:
                    if "code" not in consulta:
                        raise ValueError((consulta.get("error_description") or consulta.get(
                            "error") or ["Autorização cancelada."])[0])
                    if rota == "/oauth/youtube":
                        ger.youtube_concluir(consulta["code"][0], consulta.get("state", [""])[0])
                        texto = "Canal do YouTube conectado. Pode fechar esta aba e voltar ao painel."
                    else:
                        ger.tiktok_concluir(consulta["code"][0], consulta.get("state", [""])[0])
                        texto = "TikTok conectado. Pode fechar esta aba e voltar ao painel."
                except Exception as e:  # noqa: BLE001
                    texto = f"Não foi possível conectar: {_resumo(e)}"
                corpo = (f"<!doctype html><meta charset=utf-8><title>Cortes Virais</title>"
                         f"<body style='font:18px system-ui;padding:40px'>{html.escape(texto)}</body>"
                         ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
                return
            m = re.fullmatch(r"/midia/(\d+)", rota)
            if m:
                corte = ger.banco.corte(int(m[1]))
                if not corte:
                    return self._json({"erro": "Corte não encontrado."}, 404)
                return self._arquivo(Path(corte["arquivo"]), "video/mp4")
            m = re.fullmatch(r"/capa/(\d+)", rota)
            if m:
                corte = ger.banco.corte(int(m[1]))
                if not corte or not corte["capa"]:
                    return self._json({"erro": "Capa não encontrada."}, 404)
                return self._arquivo(Path(corte["capa"]), "image/jpeg")
            m = re.fullmatch(r"/api/analise/([^/\\]+)", unquote(rota))
            if m and ".." not in m[1]:
                arq = Path(ger.cfg["pasta_trabalho"]) / m[1] / "analise.json"
                return self._arquivo(arq, "application/json; charset=utf-8")
            self._json({"erro": "Não encontrado."}, 404)

        def do_POST(self) -> None:  # noqa: N802
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                tamanho = -1
            if not 0 <= tamanho <= seguranca.TAMANHO_MAXIMO_PEDIDO:
                self.close_connection = True
                return self._json({"erro": "Pedido grande demais."}, 413)
            corpo = self.rfile.read(tamanho) if tamanho else b"{}"
            if not self._permitido():
                return
            # Cabeçalho próprio: impede que outro site dispare ações neste painel.
            if self.headers.get("X-Painel") != "1" or not self.path.startswith("/api/"):
                return self._json({"erro": "Requisição recusada."}, 403)
            try:
                local = seguranca.host_local(self.client_address[0])
                self._json(ger.acao(self.path[len("/api/"):], json.loads(corpo or b"{}"), local))
            except (ValueError, KeyError, TypeError) as e:
                self._json({"erro": seguranca.sem_segredos(e) or "Pedido inválido."}, 400)
            except Exception as e:  # noqa: BLE001
                log.exception("Erro na ação %s", self.path)
                self._json({"erro": _resumo(e)}, 500)

    return Manipulador


def criar(cfg: dict, banco: Banco, host: str = "127.0.0.1", porta: int = 8000,
          caminho_cfg: str = "config.yaml"):
    """Cria o servidor do painel (sem iniciá-lo). Devolve (servidor, gerenciador)."""
    class Servidor(ThreadingHTTPServer):
        daemon_threads = True
        # No Windows, "reusar endereço" deixa um 2º programa ouvir na MESMA porta: os pedidos
        # se dividem entre os dois e o painel trava. Aqui a porta é exclusiva.
        allow_reuse_address = sys.platform != "win32"

        def server_bind(self) -> None:
            if sys.platform == "win32":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

        def handle_error(self, request, client_address) -> None:
            import sys
            if not isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
                super().handle_error(request, client_address)  # navegador fechando conexão é normal

    senha = os.environ.get("PAINEL_SENHA", "")
    if not seguranca.host_local(host) and len(senha) < 8:
        raise SystemExit(
            "Para abrir o painel a outros aparelhos, defina uma senha de pelo menos 8 "
            "caracteres em PAINEL_SENHA no arquivo .env. Sem isso, qualquer pessoa na sua "
            "rede poderia publicar nas suas contas.")
    servidor = Servidor((host, porta), None)
    ger = Gerenciador(cfg, banco, caminho_cfg, servidor.server_address[1])
    ger.senha = senha if not seguranca.host_local(host) else ""
    ger.hosts_aceitos = {h.strip().lower() for h in os.environ.get("PAINEL_HOSTS", "").split(",")
                         if h.strip()} if ger.senha else set()
    servidor.RequestHandlerClass = _manipulador(ger)
    return servidor, ger


def servir(cfg: dict, banco: Banco, host: str = "127.0.0.1", porta: int = 8000,
           caminho_cfg: str = "config.yaml") -> None:
    servidor, ger = criar(cfg, banco, host, porta, caminho_cfg)
    log.info("Painel em http://%s:%d", "localhost" if host in {"127.0.0.1", "0.0.0.0"} else host,
             servidor.server_address[1])
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        ger.encerrar()
        log.info("Painel encerrado.")
