"""Pipeline de vídeo gravado: baixa, analisa os sinais, escolhe e renderiza os melhores cortes."""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import numpy as np

from . import (capa, chat, compilacao, desempenho, fontes, ia, narracao, render, sinais,
               transcricao)
from .banco import Banco

log = logging.getLogger(__name__)


class Cancelado(Exception):
    """Análise interrompida pelo usuário. Os cortes já renderizados ficam."""


def _sobreposicao(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Fração do trecho menor que está dentro do outro (0 = separados, 1 = um contém o outro)."""
    comum = min(a[1], b[1]) - max(a[0], b[0])
    menor = min(a[1] - a[0], b[1] - b[0])
    return max(0.0, comum) / menor if menor > 0 else 0.0


def _termos(falas: list, inicio: float, fim: float) -> set[str]:
    return {w.lower().strip(".,!?…:;\"'") for t0, _, w in falas
            if inicio <= t0 < fim and len(w) > 2}


def repetido(c: dict, escolhidos: list[dict], existentes: list[tuple[float, float]]) -> str:
    """Motivo pelo qual o corte repete outro (vazio se não repete): o mesmo trecho do vídeo,
    ou a mesma fala dita de novo em outro ponto (o criador repete o assunto, mostra um replay)."""
    trecho = (c["inicio"], c["fim"])
    for e in existentes:
        if _sobreposicao(trecho, e) > 0.3:
            return "repete um corte já feito deste vídeo"
    meus = _termos(c.get("falas") or [], *trecho)
    for o in escolhidos:
        if _sobreposicao(trecho, (o["inicio"], o["fim"])) > 0.3:
            return "mesmo trecho de outro corte melhor"
        outros = _termos(o.get("falas") or [], o["inicio"], o["fim"])
        if len(meus) >= 8 and len(outros) >= 8 and len(meus & outros) / len(meus | outros) > 0.5:
            return "mesma fala de outro corte melhor"
    return ""


def _falas_ate(c: dict, video: Path, palavras: list, cfg: dict, ate: float) -> list:
    """Transcrição do corte garantida até `ate`, para enxergar onde a fala termina."""
    if palavras:  # legenda do YouTube: já cobre o vídeo inteiro
        return transcricao.recorte(palavras, max(0.0, c["inicio"] - 15), ate)
    falas = list(c.get("falas") or [])
    ultimo = max((p[1] for p in falas), default=c["fim"])
    if ate - ultimo > 2:
        falas += [p for p in transcricao.transcrever(video, ultimo, ate - ultimo, cfg["idioma"],
                                                     cfg["transcricao"]["whisper"])
                  if p[0] >= ultimo]
    return sorted(falas)


def fechar_bordas(c: dict, cfg: dict, duracao_video: float, video: Path | None = None,
                  palavras: list | None = None) -> None:
    """Estende o corte para a fala terminar (e começar) inteira, ajustando os tempos que
    contam do início do corte (momento-chave e narrações).

    Com IA, ela lê o que vem depois do corte e diz onde o raciocínio termina (pode alongar
    bastante, até cortes.extensao_max); sem IA, vale a próxima pausa clara da fala.
    Em ambos os casos o ponto final é encaixado numa pausa real, nunca no meio de uma palavra."""
    if not cfg["cortes"].get("fechar_frases", True):
        return
    extra = float(cfg["cortes"].get("extensao_max", 40))
    if video is not None:
        limite = c["fim"] + extra + 6
        c["falas"] = _falas_ate(c, video, palavras or [],  cfg,
                                min(limite, duracao_video) if duracao_video else limite)
    sugerido = ia.concluir_raciocinio(c, c.get("falas") or [], cfg, extra, min(10.0, c["inicio"]))
    alvo_ini, alvo_fim = sugerido or (c["inicio"], c["fim"])
    ini, fim = transcricao.fechar_fala(c.get("falas") or [], alvo_ini, alvo_fim,
                                       extra_fim=6.0 if sugerido else min(extra, 15.0),
                                       extra_inicio=min(6.0, alvo_ini))
    if duracao_video:
        fim = min(fim, duracao_video)
    fim = min(fim, ini + 180)  # Shorts e Reels aceitam até 3 minutos
    recuo = c["inicio"] - ini
    if recuo > 0:
        if c.get("momento") is not None:
            c["momento"] += recuo
        for n in c.get("narracoes") or []:
            n["segundo"] += recuo
    if (ini, fim) != (c["inicio"], c["fim"]):
        log.info("Bordas ajustadas à fala: %.1f–%.1f → %.1f–%.1f", c["inicio"], c["fim"], ini, fim)
    c["inicio"], c["fim"] = ini, fim


CAMPOS_RECEITA = ("inicio", "fim", "nota", "titulo", "descricao", "hashtags", "gancho",
                  "texto_capa", "palavras_chave", "momento", "abrir_com_pico", "narracoes",
                  "comentario_final", "notas")


def _receita(c: dict, contexto: dict, origem: str, palavras: list) -> dict:
    """Tudo o que é preciso para refazer este corte depois, com outros tempos, sem analisar
    o vídeo de novo: os textos da IA, a direção de edição e a fala em volta do trecho."""
    margem = 90  # o ajuste manual pode estender até aqui
    return {
        "versao": 1, "origem": origem,
        "corte": {k: c.get(k) for k in CAMPOS_RECEITA},
        "falas": [list(p) for p in palavras
                  if c["inicio"] - margem <= p[0] <= c["fim"] + margem],
        "contexto": {k: contexto.get(k) for k in ("id", "url", "titulo", "canal", "canal_id",
                                                  "teste", "arquivo", "duracao")},
    }


def _video_do_trecho(ctx: dict, pasta: Path, ini: float, fim: float, cfg: dict,
                     progresso) -> tuple[Path, float, Path | None]:
    """O vídeo para renderizar [ini, fim]: o original, se ainda existe, ou só esse trecho
    baixado do YouTube. Devolve (arquivo, em que segundo do original ele começa, arquivo
    temporário a apagar depois ou None)."""
    original = Path(ctx["arquivo"]) if ctx.get("arquivo") else next(
        (p for p in pasta.glob("fonte.*") if p.suffix in {".mp4", ".mkv", ".webm"}), None)
    if original and original.exists():
        return original, 0.0, None
    if not ctx.get("url"):
        raise ValueError("O vídeo original não está mais no computador.")
    progresso("Baixando o trecho do vídeo")
    inicio = max(0.0, ini)
    trecho = fontes.baixar_trecho(ctx["url"], pasta, inicio, fim, cfg["cortes"]["altura_max"])
    return trecho, inicio, trecho


def cortar_candidato(video_id: str, posicao: int, cfg: dict, banco: Banco, progresso=None) -> int:
    """Gera, em modo teste, o corte de um trecho da análise que ficou de fora (abaixo da nota,
    repetido ou fora do limite por vídeo). Você confere na aba Cortes e aprova se gostar."""
    progresso = progresso or (lambda etapa: None)
    if not re.fullmatch(r"[\w-]{1,64}", video_id or ""):
        raise ValueError("Vídeo inválido.")
    pasta = Path(cfg["pasta_trabalho"]) / video_id
    try:
        analise = json.loads((pasta / "analise.json").read_text(encoding="utf-8"))
        cand = analise["candidatos"][posicao]
    except (OSError, ValueError, IndexError, KeyError):
        raise ValueError("A análise deste vídeo não está mais disponível.") from None
    if cand.get("gerado"):
        raise ValueError("Este trecho já virou um corte.")
    for r in banco.cortes_do_video(video_id):
        if _sobreposicao((cand["inicio"], cand["fim"]), (r["inicio"], r["fim"])) > 0.3:
            raise ValueError("Este trecho já está num corte deste vídeo.")

    completos = pasta / "candidatos.json"
    receita = None
    if completos.exists():  # análises novas guardam tudo o que a IA escreveu
        lista = json.loads(completos.read_text(encoding="utf-8"))
        receita = lista[posicao] if posicao < len(lista) else None
    if receita:
        c, ctx, falas = dict(receita["corte"]), dict(receita["contexto"]), receita["falas"]
    else:  # análise de versão anterior: monta com o que ela registrou
        dados = banco._linhas("SELECT titulo, canal FROM videos WHERE id=?", (video_id,))
        titulo_video = dados[0]["titulo"] if dados else ""
        c = {"inicio": cand["inicio"], "fim": cand["fim"], "nota": cand["nota"],
             "titulo": cand.get("titulo") or titulo_video, "descricao": titulo_video,
             "hashtags": ["shorts", "cortes"], "gancho": cand.get("gancho", ""),
             "notas": cand.get("notas") or {}, "narracoes": [], "palavras_chave": []}
        ctx = {"id": video_id, "titulo": titulo_video, "canal": dados[0]["canal"] if dados else "",
               "url": analise.get("url") or f"https://www.youtube.com/watch?v={video_id}",
               "duracao": analise.get("duracao")}
        falas = None
    ctx["teste"] = True  # sempre em teste: você vê o vídeo pronto antes de publicar

    extra = float(cfg["cortes"].get("extensao_max", 40)) if cfg["cortes"].get("fechar_frases", True) else 0
    video, deslocamento, trecho = _video_do_trecho(
        ctx, pasta, c["inicio"] - 12, c["fim"] + extra + 8, cfg, progresso)
    try:
        if falas is None:  # sem transcrição guardada: transcreve o trecho baixado
            progresso("Transcrevendo o trecho")
            falas = [(a + deslocamento, b + deslocamento, w) for a, b, w in transcricao.transcrever(
                video, max(0.0, c["inicio"] - 12 - deslocamento), c["fim"] - c["inicio"] + extra + 20,
                cfg["idioma"], cfg["transcricao"]["whisper"])]
        c["falas"] = [tuple(p) for p in falas]
        progresso("Conferindo o fim da fala")
        fechar_bordas(c, cfg, ctx.get("duracao") or 0)
        c["inicio_arquivo"] = c["inicio"] - deslocamento
        c["fim_arquivo"] = c["fim"] - deslocamento
        progresso("Renderizando")
        relativas = [(a - deslocamento, b - deslocamento, w) for a, b, w in c["falas"]]
        corte_id = finalizar(c, video, ctx, cfg, banco, pasta, "vod", relativas,
                             deslocamento=deslocamento)
    finally:
        if trecho:
            trecho.unlink(missing_ok=True)
    cand.update(gerado=corte_id, situacao="cortado", escolhido=True)
    (pasta / "analise.json").write_text(json.dumps(analise, ensure_ascii=False), encoding="utf-8")
    return corte_id


def arquivo_receita(arquivo_corte: str | Path, corte_id: int) -> Path:
    return Path(arquivo_corte).parent / f"receita_{corte_id}.json"


def pode_refazer(corte) -> bool:
    return (not corte["yt_id"] and not corte["ig_id"]
            and arquivo_receita(corte["arquivo"], corte["id"]).exists())


def refazer(corte_id: int, ajuste_inicio: float, ajuste_fim: float, cfg: dict, banco: Banco,
            progresso=None) -> None:
    """Renderiza de novo um corte com o começo e/ou o fim mudados (segundos; negativo =
    antes). Usa a receita guardada: não analisa o vídeo de novo. Se o vídeo original já foi
    apagado, baixa só o trecho necessário."""
    progresso = progresso or (lambda etapa: None)
    row = banco.corte(corte_id)
    if not row:
        raise ValueError("Corte não encontrado.")
    if row["yt_id"] or row["ig_id"]:
        raise ValueError("Este corte já foi publicado: não dá para refazê-lo.")
    arq_rec = arquivo_receita(row["arquivo"], corte_id)
    if not arq_rec.exists():
        raise ValueError("Este corte é de uma versão anterior do programa e não pode ser "
                         "ajustado. Envie o vídeo de novo para gerar cortes ajustáveis.")
    receita = json.loads(arq_rec.read_text(encoding="utf-8"))
    c, ctx = dict(receita["corte"]), receita["contexto"]
    ini = max(0.0, float(row["inicio"]) + float(ajuste_inicio))
    fim = float(row["fim"]) + float(ajuste_fim)
    if ctx.get("duracao"):
        fim = min(fim, float(ctx["duracao"]))
    if fim - ini < 5:
        raise ValueError("O corte ficaria curto demais (mínimo de 5 segundos).")
    if fim - ini > 180:
        raise ValueError("O corte ficaria longo demais (Shorts e Reels aceitam até 3 minutos).")

    # Tempos contados do começo do corte acompanham a mudança do início.
    desloc = ini - float(c["inicio"])
    if c.get("momento") is not None:
        m = float(c["momento"]) - desloc
        c["momento"] = m if 0 <= m <= fim - ini else None
    c["narracoes"] = [{**n, "segundo": n["segundo"] - desloc} for n in c.get("narracoes") or []
                      if 0 <= n["segundo"] - desloc < fim - ini]
    c["inicio"], c["fim"] = ini, fim

    pasta = Path(row["arquivo"]).parent
    video, deslocamento, trecho = _video_do_trecho(ctx, pasta, ini - 1, fim + 1, cfg, progresso)
    c["inicio_arquivo"], c["fim_arquivo"] = ini - deslocamento, fim - deslocamento
    falas = [(a - deslocamento, b - deslocamento, w) for a, b, w in receita["falas"]]

    progresso("Renderizando")
    saida = pasta / f"corte_{corte_id}_v{int(time.time())}.mp4"
    try:
        feito = montar(c, video, ctx, cfg, saida, falas, banco)
    finally:
        if trecho:
            trecho.unlink(missing_ok=True)
    antigo_video, antiga_capa = Path(row["arquivo"]), Path(row["capa"]) if row["capa"] else None
    banco.atualizar_corte(corte_id, inicio=ini, fim=fim, arquivo=str(saida), descricao=feito["descricao"],
                          capa=feito["capa"], capa_ms=feito["capa_ms"], layout=feito["layout"],
                          narracao=feito["narracao"])
    for velho in (antigo_video, antiga_capa):
        if velho and velho != saida and velho.exists():
            try:
                velho.unlink()
            except OSError:  # aberto em outro lugar (player, envio): fica para a limpeza
                log.warning("Não foi possível apagar %s", velho)
    receita["corte"] = {k: c.get(k) for k in CAMPOS_RECEITA}
    arq_rec.write_text(json.dumps(receita, ensure_ascii=False), encoding="utf-8")
    log.info("Corte %s refeito: %.1f–%.1f s", corte_id, ini, fim)


PLATAFORMAS_CFG = {"yt": "youtube", "ig": "instagram", "tt": "tiktok"}


def publicacao_automatica(c: dict, contexto: dict, cfg: dict,
                          origem: str = "vod") -> tuple[list[str], bool]:
    """(plataformas para as quais o corte vai sozinho, publica já sem esperar intervalo e
    horário), pela nota da IA. Cada plataforma decide se aceita publicação automática
    (publicar.<plataforma>.automatico): nas desligadas o corte sempre espera você.
    Regras, nas ligadas: nota acima de publicar.auto_acima vai sozinho; corte de live com
    nota acima de publicar.<plataforma>.auto_live_acima também; acima de imediato_acima,
    sai na hora. Só vale a nota da IA de nuvem (a da IA local e a sem IA vêm das métricas,
    em outra escala). Vídeos em modo teste nunca publicam sozinhos."""
    p = cfg["publicar"]
    confiavel = (not contexto.get("teste") and not c.get("validado_local")
                 and not str(c.get("motivo", "")).startswith("sem IA"))
    if not confiavel:
        return [], False
    nota = float(c.get("nota") or 0)
    auto_acima, imediato_acima = float(p.get("auto_acima", 88)), float(p.get("imediato_acima", 90))
    plats = []
    for sigla, nome in PLATAFORMAS_CFG.items():
        cfg_p = p.get(nome) or {}
        if not cfg_p.get("automatico", True):
            continue
        limite_live = float(cfg_p.get("auto_live_acima") or 0)
        if (auto_acima > 0 and nota > auto_acima) or (imediato_acima > 0 and nota > imediato_acima) \
                or (origem == "live" and limite_live > 0 and nota > limite_live):
            plats.append(sigla)
    imediato = bool(plats) and imediato_acima > 0 and nota > imediato_acima
    return plats, imediato


def finalizar(c: dict, video: Path, contexto: dict, cfg: dict, banco: Banco, pasta: Path,
              origem: str, palavras: list, urgente: bool = False, deslocamento: float = 0.0) -> int:
    """Renderiza um corte aprovado e o coloca na fila de publicação. `deslocamento` é o
    segundo do vídeo original em que `video` começa (quando é só um trecho baixado)."""
    saida = pasta / f"corte_{int(c['inicio']):06d}.mp4"
    feito = montar(c, video, contexto, cfg, saida, palavras, banco)
    auto, imediato = publicacao_automatica(c, contexto, cfg, origem)
    urgente = urgente or imediato
    manual = cfg["publicar"].get("manual", True) and not contexto.get("teste")
    corte_id = banco.novo_corte(
        video_id=contexto["id"], origem=origem, inicio=c["inicio"], fim=c["fim"], nota=c["nota"],
        titulo=c["titulo"], descricao=feito["descricao"], hashtags=c["hashtags"], arquivo=saida,
        urgente=urgente, teste=bool(contexto.get("teste")),
        gancho=c.get("gancho", "").replace("*", ""), capa=feito["capa"], capa_ms=feito["capa_ms"],
        notas=c.get("notas"), layout=feito["layout"], narracao=feito["narracao"],
        # Com publicação manual (padrão), o corte espera você decidir em todas as plataformas;
        # logo abaixo, as que aceitam publicação automática e cuja regra de nota bateu são
        # liberadas (as outras continuam esperando você).
        aguardando=manual)
    if manual and auto:
        banco.aprovar(corte_id, auto)
    if auto:
        nomes = ", ".join(PLATAFORMAS_CFG[x] for x in auto)
        log.info("Corte %s com nota %.0f: %s (%s)", corte_id, c["nota"],
                 "publicação imediata" if imediato else "entra sozinho na fila", nomes)
    if origem == "vod":  # cortes de live não guardam o vídeo de origem para refazer
        originais = [(a + deslocamento, b + deslocamento, w) for a, b, w in palavras]
        arquivo_receita(saida, corte_id).write_text(
            json.dumps(_receita(c, contexto, origem, originais), ensure_ascii=False), encoding="utf-8")
    log.info("Corte %s pronto: [%.0fs–%.0fs] nota %.0f — %s", corte_id, c["inicio"], c["fim"],
             c["nota"], c["titulo"])
    return corte_id


def montar(c: dict, video: Path, contexto: dict, cfg: dict, saida: Path, palavras: list,
           banco: Banco | None = None) -> dict:
    """Renderiza o vídeo e a capa de um corte. `inicio_arquivo`/`fim_arquivo`, quando
    presentes, são os tempos dentro de `video` (que pode ser só um trecho do original)."""
    ini = c.get("inicio_arquivo", c["inicio"])
    fim = c.get("fim_arquivo", c["fim"])
    canal = contexto.get("canal", "")
    creditar = cfg["publicar"]["creditar_fonte"] and canal
    momento = c.get("momento")
    falas, final = narracao.preparar(c, saida, ini, cfg)
    feito = render.renderizar(
        video, ini, fim, saida, formato=cfg["cortes"]["formato"], palavras=palavras,
        credito=f"Créditos: {canal}" if creditar else "",
        gancho=c.get("gancho", "") if cfg["cortes"]["gancho"] else "",
        marca=cfg["cortes"]["marca"], palavras_chave=c.get("palavras_chave"),
        momento=None if momento is None else ini + momento,
        abrir_com_pico=bool(c.get("abrir_com_pico")), narracoes=falas, encerramento=final,
        cfg_cortes=cfg["cortes"], cfg_edicao=cfg["edicao"],
    )
    layout = feito["layout"]
    arq_capa, capa_ms = "", None
    if cfg["cortes"]["capa"] and layout != "original":
        instante = feito["momento"] if feito["momento"] is not None else ini + (fim - ini) * 0.4
        texto = c.get("texto_capa") or c.get("gancho") or " ".join(c["titulo"].split()[:3])
        arq_capa = capa.gerar(video, instante, saida.with_suffix(".capa.jpg"), texto,
                              cena=feito["cena"], dimensoes=feito["dimensoes"],
                              cores=transcricao.tema(cfg["cortes"]),
                              marca=cfg["cortes"]["marca"]) or ""
        if feito["momento_saida"] is not None:  # no Instagram, a capa é este quadro do vídeo
            capa_ms = int(feito["momento_saida"] * 1000)
    descricao = c["descricao"]
    if creditar and contexto.get("url"):
        sep = "&" if "?" in contexto["url"] else "?"
        descricao += f"\n\nFonte: {canal} — {contexto['url']}{sep}t={int(c['inicio'])}s"
    campanha = banco.canal(contexto.get("canal_id")) if banco else None
    if campanha and campanha["texto_obrigatorio"]:  # exigência da campanha paga do canal
        descricao += f"\n\n{campanha['texto_obrigatorio']}"
    return {"descricao": descricao, "capa": str(arq_capa) if arq_capa else "", "capa_ms": capa_ms,
            "layout": layout,
            "narracao": " / ".join([f["texto"] for f in falas] + ([final["texto"]] if final else []))}


def _marcada(falas: list, inicio: float, fim: float) -> str:
    """Transcrição com o tempo relativo ao início do corte, para a IA ajustar as bordas."""
    partes, ultimo = [], None
    for t0, _, palavra in falas:
        marca = int((t0 - inicio) // 5) * 5
        if marca != ultimo:
            partes.append(f"[{marca:+d}s]")
            ultimo = marca
        partes.append(palavra)
    return " ".join(partes) + f"  (corte atual: 0s a {fim - inicio:.0f}s)"


def _reduzir(serie, pontos: int = 600) -> list[float]:
    """Encolhe uma série por segundo para o gráfico, guardando o máximo de cada trecho."""
    serie = np.asarray(serie, dtype=np.float32)
    if len(serie) <= pontos:
        return [round(float(v), 2) for v in serie]
    bordas = np.linspace(0, len(serie), pontos + 1).astype(int)
    return [round(float(serie[a:b].max()), 2) for a, b in zip(bordas[:-1], bordas[1:])]


def processar(alvo: str, cfg: dict, banco: Banco, *, chat_arquivo: str | None = None,
              forcar: bool = False, meta: dict | None = None, progresso=None) -> list[int]:
    """Processa uma URL do YouTube ou arquivo local. Devolve os IDs dos cortes criados.

    Com meta["teste"], os cortes são gerados mas ficam fora da fila de publicação.
    """
    progresso = progresso or (lambda etapa, fracao=None: None)
    meta = meta or fontes.info(alvo)
    if meta["ao_vivo"]:
        raise ValueError("Este vídeo está ao vivo: use o comando 'live'.")
    if banco.status_video(meta["id"]) and not forcar:
        log.info("%s já foi processado; use --forcar para repetir.", meta["id"])
        return []
    limite = cfg["fontes"].get("duracao_max_h", 6) * 3600
    if meta["duracao"] > limite:
        log.warning("%s tem %.1f h, acima de fontes.duracao_max_h; ignorado.", meta["id"],
                    meta["duracao"] / 3600)
        return []
    log.info("Analisando: %s (%s)", meta["titulo"], meta["canal"] or "arquivo local")
    pasta = Path(cfg["pasta_trabalho"]) / meta["id"]
    pasta.mkdir(parents=True, exist_ok=True)

    if "arquivo" in meta:
        arquivos = {"video": Path(meta["arquivo"]), "chat": chat_arquivo, "legenda": None}
    else:
        progresso("Baixando o vídeo", 0.0)
        arquivos = fontes.baixar(meta["url"], pasta, cfg["cortes"]["altura_max"], cfg["idioma"],
                                 progresso)
    video = Path(arquivos["video"])
    mensagens = chat.ler_replay(arquivos["chat"]) if arquivos["chat"] else []
    palavras = transcricao.ler_json3(arquivos["legenda"]) if arquivos["legenda"] else []

    # 1. Sinais -> candidatos (o triplo do necessário, para a IA escolher).
    progresso("Medindo chat, áudio e replays")
    pontuacao, usados = sinais.analisar(
        audio=sinais.volume_por_segundo(video), mensagens=mensagens, replay=meta["replay"],
        duracao=meta["duracao"], cfg=cfg)
    log.info("Sinais usados: %s", ", ".join(sorted(usados)))
    duracao = cfg["cortes"]["duracao"]
    janelas = sinais.melhores_janelas(pontuacao, duracao, cfg["cortes"]["por_video"] * 3,
                                      cfg["cortes"]["intervalo_minimo"])

    # 2. Transcrição e ajuste das bordas para não cortar frases.
    candidatos = []
    for n_jan, (inicio, nota) in enumerate(janelas):
        progresso(f"Transcrevendo candidato {n_jan + 1} de {len(janelas)}", n_jan / len(janelas))
        # Não corta com o pico ainda no alto: a janela cresce até a empolgação baixar.
        inicio, fim = sinais.ajustar_ao_pico(pontuacao, inicio, duracao)
        fim = min(fim, meta["duracao"] or fim)
        # Margem larga: a IA pode adiantar o início ou estender o fim do corte, e o fim
        # ainda pode crescer até a fala terminar (cortes.extensao_max).
        antes, depois = 9, 16 + min(15, int(cfg["cortes"].get("extensao_max", 40)))
        falas = transcricao.recorte(palavras, inicio - antes, fim + depois) or transcricao.transcrever(
            video, max(0, inicio - antes), fim - inicio + antes + depois, cfg["idioma"],
            cfg["transcricao"]["whisper"])
        ini_aj, fim_aj = transcricao.ajustar_bordas(falas, float(inicio), fim)
        candidatos.append({
            "inicio": ini_aj, "fim": fim_aj, "pontuacao": nota, "falas": falas,
            "folga_inicio": min(8, ini_aj),
            "folga_fim": max(0, min(15, (meta["duracao"] or fim_aj + 15) - fim_aj)),
            "transcricao": _marcada(falas, ini_aj, fim_aj),
            "chat": chat.trecho(mensagens, ini_aj, fim_aj + cfg["sinais"]["atraso_chat"]),
        })

    # 3. Triagem rápida (texto) e depois o julgamento final (com imagens) dos melhores.
    if ia.disponivel(cfg):
        progresso("Triagem rápida dos candidatos")
        candidatos = ia.triar(candidatos, meta, cfg, manter=cfg["cortes"]["por_video"] * 2)
    progresso("Avaliando com IA" if ia.disponivel(cfg) else "Ordenando pelos sinais")
    meta["referencias"] = desempenho.referencias(banco)
    avaliados = ia.avaliar(candidatos, meta, video, cfg)
    # Validados pela IA local têm nota só das métricas, em outra escala: a nota mínima (pensada
    # para a IA de nuvem) não vale para eles; entram os aprovados, na ordem das métricas.
    bons = [c for c in avaliados if c["aprovado"]
            and (c.get("validado_local") or c["nota"] >= cfg["ia"]["nota_minima"])]
    bons.sort(key=lambda c: c["nota"], reverse=True)
    # Do melhor para o pior: fecha as falas e pula o que repete um corte já escolhido
    # (ou já feito deste vídeo numa análise anterior), abrindo vaga para o próximo da lista.
    existentes = [(r["inicio"], r["fim"]) for r in banco.cortes_do_video(meta["id"])]
    escolhidos = []
    for c in bons:
        if len(escolhidos) >= cfg["cortes"]["por_video"]:
            break
        progresso(f"Conferindo o fim da fala ({len(escolhidos) + 1} de {cfg['cortes']['por_video']})")
        fechar_bordas(c, cfg, meta["duracao"], video, palavras)
        motivo = repetido(c, escolhidos, existentes)
        if motivo:
            c["repetido"] = motivo
            log.info("Descartado por repetição (%s): %s", motivo, c.get("titulo", ""))
            continue
        escolhidos.append(c)
    log.info("%d candidatos, %d aprovados, %d escolhidos.", len(candidatos), len(bons),
             len(escolhidos))

    # Registro da análise, para o painel mostrar o que foi considerado e por quê.
    nota_min = cfg["ia"]["nota_minima"]

    def situacao(c: dict) -> str:
        if c in escolhidos:
            return "cortado"
        if not c["aprovado"]:
            return "reprovado"
        if c["nota"] < nota_min and not c.get("validado_local"):
            return "abaixo"
        return "repetido" if c.get("repetido") else "fora"

    ordem = sorted(avaliados, key=lambda c: c["inicio"])
    (pasta / "analise.json").write_text(json.dumps({
        "video_id": meta["id"], "url": meta.get("url", ""),
        "duracao": meta["duracao"], "com_ia": ia.disponivel(cfg), "nota_minima": nota_min,
        "pontos": _reduzir(pontuacao),
        "sinais": {nome: _reduzir(serie) for nome, serie in usados.items()},
        "candidatos": [{
            "inicio": round(c["inicio"], 1), "fim": round(c["fim"], 1), "nota": c["nota"],
            "aprovado": c["aprovado"], "escolhido": c in escolhidos, "situacao": situacao(c),
            "titulo": c["titulo"],
            "motivo": c["motivo"] + (f" — descartado: {c['repetido']}" if c.get("repetido") else ""),
            "gancho": c.get("gancho", "").replace("*", ""), "notas": c.get("notas") or {},
            "transcricao": c.get("transcricao", "")[:400],
        } for c in ordem],
    }, ensure_ascii=False), encoding="utf-8")
    # Dados completos de cada candidato, na mesma ordem, para você poder cortar depois um
    # trecho que ficou de fora sem analisar o vídeo de novo.
    (pasta / "candidatos.json").write_text(json.dumps([
        _receita(c, meta, "vod", c.get("falas") or []) for c in ordem], ensure_ascii=False),
        encoding="utf-8")

    # 4. Renderização.
    criados = []
    for i, c in enumerate(escolhidos):
        progresso(f"Renderizando corte {i + 1} de {len(escolhidos)}", i / len(escolhidos))
        criados.append(finalizar(c, video, meta, cfg, banco, pasta, "vod", c["falas"]))
    try:
        if len(escolhidos) >= cfg["compilacao"]["minimo"] and cfg["compilacao"]["ativa"]:
            progresso("Montando a compilação narrada")
            comp = compilacao.montar(video, escolhidos, meta, cfg, banco, pasta)
            if comp:
                criados.append(comp)
    except Exception:  # noqa: BLE001 — a compilação é um extra: os cortes já estão prontos
        log.exception("Falha ao montar a compilação")
    banco.marcar_video(meta["id"], meta["titulo"], meta["canal"],
                       "teste" if meta.get("teste") else "feito")
    if cfg["cortes"]["apagar_fonte"] and "arquivo" not in meta:
        for p in pasta.glob("fonte.*"):
            p.unlink()
    return criados
