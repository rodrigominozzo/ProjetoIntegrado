"""Fila de publicação: respeita limites diários e espaçamento entre posts."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import seguranca
from ..banco import Banco
from . import instagram, tiktok, youtube

log = logging.getLogger(__name__)
NOMES = {"yt": "youtube", "ig": "instagram", "tt": "tiktok"}
ROTULOS = {"yt": "YouTube", "ig": "Instagram", "tt": "TikTok"}
ESPERA_LIMITE_TT_S = 3600  # o TikTok recusou por limite: tenta de novo depois de 1 h
ESPERA_LIMITE_YT_S = 2 * 3600  # o YouTube recusou por limite diário do canal: 2 h depois
# Envios em andamento: (corte, plataforma) -> {"etapa", "fracao" (0–1 ou None), "inicio"}.
# Mostra o andamento no painel e impede o mesmo corte de ser enviado duas vezes ao mesmo tempo.
ENVIANDO: dict[tuple[int, str], dict] = {}
_trava_envio = threading.Lock()
# Falhas de processamento do Instagram (passageiras): rodadas por corte e quando tentar de novo.
ESPERAS_IG_MIN = [15, 45, 120, 240]   # minutos de espera após a 1ª, 2ª, 3ª... rodada falha
MAX_FALHAS_IG = 6                     # rodadas (cada uma já tenta 3 versões) antes de desistir
_falhas_ig: dict[int, int] = {}
_esperar_ate: dict[tuple[int, str], float] = {}
VERIFICACAO_S = 30  # o painel tenta publicar a fila a cada 30 s


def janelas(texto: str) -> list[tuple[int, int]]:
    """Converte "11:00-14:00, 18:00-23:30" em pares de minutos do dia."""
    pares = []
    for trecho in filter(None, (t.strip() for t in texto.split(","))):
        m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", trecho)
        if not m or int(m[1]) > 23 or int(m[3]) > 24 or int(m[2]) > 59 or int(m[4]) > 59:
            raise ValueError("Escreva os horários assim: 11:00-14:00, 18:00-23:30")
        pares.append((int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])))
    return pares


def no_horario(cfg: dict, agora: float | None = None) -> bool:
    """Estamos numa das janelas de postagem? Sem janelas configuradas, sempre."""
    try:
        pares = janelas(cfg["publicar"].get("horarios", ""))
    except ValueError:
        return True
    if not pares:
        return True
    t = time.localtime(agora)
    minuto = t.tm_hour * 60 + t.tm_min
    return any(a <= minuto < b if a <= b else (minuto >= a or minuto < b) for a, b in pares)


def conectado(plataforma: str, cfg: dict) -> bool:
    """A conta de destino está configurada? Sem isso a plataforma é pulada, sem gastar tentativas."""
    if plataforma == "yt":
        return Path(cfg["publicar"]["youtube"]["token"]).exists()
    if plataforma == "tt":
        return tiktok.conectado(cfg["publicar"]["tiktok"])
    return bool(os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"))


def _texto(corte, plataforma: str) -> str:
    marcas = " ".join(f"#{h}" for h in json.loads(corte["hashtags"] or "[]"))
    if plataforma == "ig":
        return f"{corte['titulo']}\n\n{corte['descricao']}\n\n{marcas}".strip()
    return f"{corte['descricao']}\n\n{marcas}".strip()


def enviando(corte_id: int, plataforma: str) -> bool:
    return (corte_id, plataforma) in ENVIANDO


def publicar_um(cfg: dict, banco: Banco, corte, plataforma: str) -> bool:
    """Envia um corte para uma plataforma e registra o resultado."""
    nome = NOMES[plataforma]
    cfg_p = cfg["publicar"][nome]
    chave = (corte["id"], plataforma)
    with _trava_envio:
        if chave in ENVIANDO:  # já está indo (botão clicado duas vezes, ou a fila automática)
            return False
        andamento = {"etapa": "Preparando", "fracao": None, "inicio": time.time()}
        ENVIANDO[chave] = andamento

    def progresso(etapa: str, fracao: float | None = None) -> None:
        andamento.update(etapa=etapa, fracao=fracao)

    try:
        if not Path(corte["arquivo"]).exists():
            raise FileNotFoundError("arquivo do corte não existe mais")
        if plataforma == "yt":
            remoto = youtube.enviar(corte["arquivo"], corte["titulo"], _texto(corte, "yt"),
                                    json.loads(corte["hashtags"] or "[]"), cfg_p,
                                    curto=corte["origem"] != "compilacao",
                                    capa=corte["capa"] or "", progresso=progresso)
            link = (f"https://youtu.be/{remoto}" if corte["origem"] == "compilacao"
                    else f"https://youtube.com/shorts/{remoto}")
        elif plataforma == "tt":
            remoto, link = tiktok.enviar(corte["arquivo"], cfg_p, progresso=progresso)
        else:
            remoto, link = instagram.enviar(corte["arquivo"], _texto(corte, "ig"), cfg_p,
                                            capa_ms=corte["capa_ms"], progresso=progresso)
    except tiktok.LimiteTikTok as e:
        # Limite do TikTok (5 pendentes em 24 h): não é defeito do corte nem gasta tentativa.
        _esperar_ate[(corte["id"], plataforma)] = time.time() + ESPERA_LIMITE_TT_S
        quando = datetime.fromtimestamp(time.time() + ESPERA_LIMITE_TT_S).strftime("%H:%M")
        banco.falhou(corte["id"], plataforma, f"{e} Nova tentativa às {quando}.", contar=False)
        log.warning("TikTok no limite ao enviar o corte %s; nova tentativa às %s.", corte["id"], quando)
        return False
    except instagram.FalhaProcessamento as e:
        # Falha passageira do Instagram: não gasta tentativa; volta sozinho mais tarde, com
        # espera crescente (insistir em sequência só acumula recusas). Desiste após várias.
        n = _falhas_ig.get(corte["id"], 0) + 1
        _falhas_ig[corte["id"]] = n
        if n >= MAX_FALHAS_IG:
            erro = f"{e} Desisti depois de {n} rodadas; use Publicar agora para tentar de novo."
            banco.falhou(corte["id"], plataforma, erro)
            log.error("Falha ao publicar corte %s no %s: %s", corte["id"], nome, erro)
            return False
        espera = ESPERAS_IG_MIN[min(n, len(ESPERAS_IG_MIN)) - 1] * 60
        _esperar_ate[(corte["id"], plataforma)] = time.time() + espera
        quando = datetime.fromtimestamp(time.time() + espera).strftime("%H:%M")
        banco.falhou(corte["id"], plataforma, f"{e} Nova tentativa automática às {quando}.",
                     contar=False)
        log.warning("Instagram falhou ao processar o corte %s (rodada %d); nova tentativa às %s.",
                    corte["id"], n, quando)
        return False
    except Exception as e:  # noqa: BLE001
        erro = seguranca.sem_segredos(e)
        limite_yt = plataforma == "yt" and "uploadLimitExceeded" in str(e)
        # Instagram: limite de publicações da conta em 24 h (a Meta fala em 50 ou 100) ou de
        # chamadas à API — códigos 4, 9, 17, 32 e 613, ou mensagens de limite.
        limite_ig = plataforma == "ig" and bool(re.search(
            r"\(#(4|9|17|32|613)\)|\bcode\W{0,3}(4|9|17|32|613)\b|rate limit|request limit"
            r"|limit (has been )?reached|publishing limit|too many (calls|requests|posts)", str(e), re.I))
        if limite_yt or limite_ig:
            # Limite diário da própria plataforma (não é o max_por_dia daqui): o corte não tem
            # defeito; espera e tenta de novo sem gastar tentativa.
            espera = ESPERA_LIMITE_YT_S
            _esperar_ate[(corte["id"], plataforma)] = time.time() + espera
            quando = datetime.fromtimestamp(time.time() + espera).strftime("%H:%M")
            texto = ("O YouTube atingiu o limite diário de envios do canal." if limite_yt else
                     "O Instagram atingiu o limite de publicações da conta em 24 h.")
            banco.falhou(corte["id"], plataforma, f"{texto} Nova tentativa às {quando}.", contar=False)
            log.warning("%s no limite; corte %s volta às %s. (%s)", nome, corte["id"], quando,
                        erro[:200])
            return False
        log.error("Falha ao publicar corte %s no %s: %s", corte["id"], nome, erro)
        banco.falhou(corte["id"], plataforma, erro)
        return False
    finally:
        with _trava_envio:
            ENVIANDO.pop(chave, None)
    _falhas_ig.pop(corte["id"], None)
    _esperar_ate.pop((corte["id"], plataforma), None)
    banco.publicado(corte["id"], plataforma, remoto, link)
    log.info("Publicado no %s: %s (%s)", nome, corte["titulo"], remoto)
    return True


def _proxima_janela(t: float, pares: list[tuple[int, int]]) -> float:
    """O primeiro instante a partir de `t` dentro de um horário de postagem."""
    if not pares:
        return t
    for dia in range(3):
        meia_noite = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0)
        base = meia_noite.timestamp() + dia * 86400
        opcoes = []
        for a, b in pares:
            for ini, fim in ([(a, b)] if a <= b else [(a, 1440), (0, b)]):
                if base + fim * 60 > t:
                    opcoes.append(max(t, base + ini * 60))
        if opcoes:
            return min(opcoes)
    return t


def previsao(cfg: dict, banco: Banco, agora: float | None = None) -> dict:
    """Quando cada corte da fila deve sair, simulando as mesmas regras de publicar_pendentes:
    urgentes primeiro, intervalo entre posts, limite em 24 h e horários de postagem.
    Devolve {plataforma: {"bloqueio": "" | "pausada" | "desativada" | "sem_conta",
    "cortes": {id: {"posicao", "quando" (timestamp ou None), "motivo"}}}}."""
    agora = agora or time.time()
    intervalo = cfg["publicar"]["intervalo_min"] * 60
    try:
        pares = janelas(cfg["publicar"].get("horarios", ""))
    except ValueError:
        pares = []
    pausada = banco.opcao("publicacao_auto", "1") != "1"
    resultado = {}
    for plataforma, nome in NOMES.items():
        cfg_p = cfg["publicar"][nome]
        bloqueio = ("desativada" if not cfg_p["ativo"] else "sem_conta"
                    if not conectado(plataforma, cfg) else "pausada" if pausada else "")
        recentes = banco.publicacoes_desde(plataforma, agora - 86400)
        ultima = banco.ultima_publicacao(plataforma)
        maximo = cfg_p["max_por_dia"]
        cortes = {}
        for pos, c in enumerate((c for c in banco.pendentes(plataforma)
                                 if not enviando(c["id"], plataforma)), 1):
            if bloqueio or maximo <= 0:
                cortes[c["id"]] = {"posicao": pos, "quando": None,
                                   "motivo": bloqueio or "limite_zero"}
                continue
            motivo = "agora"
            t = agora
            if _esperar_ate.get((c["id"], plataforma), 0) > t:  # nova tentativa marcada
                t, motivo = _esperar_ate[(c["id"], plataforma)], "nova_tentativa"
            if not c["urgente"]:
                if ultima + intervalo > t:
                    t, motivo = ultima + intervalo, "intervalo"
                janela = _proxima_janela(t, pares)
                if janela > t:
                    t, motivo = janela, "horario"
            for _ in range(maximo + 2):  # limite de posts em 24 h (janela móvel)
                no_periodo = sorted(x for x in recentes if x > t - 86400)
                if len(no_periodo) < maximo:
                    break
                t, motivo = max(t, no_periodo[len(no_periodo) - maximo] + 86400 + 1), "limite"
                if not c["urgente"]:
                    t = _proxima_janela(t, pares)
            if motivo == "agora":
                t = agora + VERIFICACAO_S  # sai na próxima verificação da fila
            elif motivo == "intervalo" and t - agora > 86400:
                # Mais de um dia de espera não é o intervalo de minutos: é o limite diário
                # (de cortes anteriores) empurrando a fila inteira.
                motivo = "limite"
            cortes[c["id"]] = {"posicao": pos, "quando": t, "motivo": motivo}
            recentes.append(t)
            ultima = max(ultima, t)
        resultado[plataforma] = {"bloqueio": bloqueio, "cortes": cortes}
    return resultado


_avisou_limite: dict[str, float] = {}


def publicar_pendentes(cfg: dict, banco: Banco) -> int:
    """Publica o que couber agora nos limites. Devolve quantos posts foram feitos."""
    if banco.opcao("publicacao_auto", "1") != "1":
        return 0  # pausada pelo painel
    feitos = 0
    for plataforma, nome in NOMES.items():
        cfg_p = cfg["publicar"][nome]
        if not cfg_p["ativo"] or not conectado(plataforma, cfg):
            continue
        for corte in banco.pendentes(plataforma):
            if enviando(corte["id"], plataforma):
                continue  # já está sendo enviado (ex.: "Publicar agora")
            if _esperar_ate.get((corte["id"], plataforma), 0) > time.time():
                continue  # falha passageira há pouco: espera a hora da nova tentativa
            if banco.publicados_desde(plataforma, time.time() - 86400) >= cfg_p["max_por_dia"]:
                # Avisa uma vez por hora, não a cada ciclo de 30 s (enchia o log).
                if time.time() - _avisou_limite.get(plataforma, 0) >= 3600:
                    _avisou_limite[plataforma] = time.time()
                    log.info("Limite diário do %s atingido; o restante fica na fila.", nome)
                break
            espacado = (time.time() - banco.ultima_publicacao(plataforma)
                        >= cfg["publicar"]["intervalo_min"] * 60)
            if not corte["urgente"] and not (espacado and no_horario(cfg)):
                continue  # cortes de live furam a fila; os demais esperam intervalo e horário
            feitos += publicar_um(cfg, banco, corte, plataforma)
    return feitos
