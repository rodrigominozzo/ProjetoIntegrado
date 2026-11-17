"""Pipeline de vídeo gravado: baixa, analisa os sinais, escolhe e renderiza os melhores cortes."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from . import chat, desempenho, fontes, ia, render, sinais, transcricao
from .banco import Banco

log = logging.getLogger(__name__)


def finalizar(c: dict, video: Path, contexto: dict, cfg: dict, banco: Banco, pasta: Path,
              origem: str, palavras: list, urgente: bool = False) -> int:
    """Renderiza um corte aprovado e o coloca na fila de publicação."""
    ini = c.get("inicio_arquivo", c["inicio"])
    fim = c.get("fim_arquivo", c["fim"])
    canal = contexto.get("canal", "")
    creditar = cfg["publicar"]["creditar_fonte"] and canal
    saida = pasta / f"corte_{int(c['inicio']):06d}.mp4"
    momento = c.get("momento")
    feito = render.renderizar(
        video, ini, fim, saida, formato=cfg["cortes"]["formato"], palavras=palavras,
        credito=f"Créditos: {canal}" if creditar else "",
        gancho=c.get("gancho", "") if cfg["cortes"]["gancho"] else "",
        marca=cfg["cortes"]["marca"], palavras_chave=c.get("palavras_chave"),
        momento=None if momento is None else ini + momento,
        abrir_com_pico=bool(c.get("abrir_com_pico")),
        cfg_cortes=cfg["cortes"], cfg_edicao=cfg["edicao"],
    )
    layout = feito["layout"]
    descricao = c["descricao"]
    if creditar and contexto.get("url"):
        sep = "&" if "?" in contexto["url"] else "?"
        descricao += f"\n\nFonte: {canal} — {contexto['url']}{sep}t={int(c['inicio'])}s"
    corte_id = banco.novo_corte(
        video_id=contexto["id"], origem=origem, inicio=c["inicio"], fim=c["fim"], nota=c["nota"],
        titulo=c["titulo"], descricao=descricao, hashtags=c["hashtags"], arquivo=saida,
        urgente=urgente, teste=bool(contexto.get("teste")), gancho=c.get("gancho", ""),
        notas=c.get("notas"), layout=layout)
    log.info("Corte %s pronto: [%.0fs–%.0fs] nota %.0f — %s", corte_id, c["inicio"], c["fim"],
             c["nota"], c["titulo"])
    return corte_id


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
    progresso("Transcrevendo os candidatos")
    candidatos = []
    for inicio, nota in janelas:
        fim = min(float(inicio + duracao), meta["duracao"] or inicio + duracao)
        # Margem larga: a IA pode adiantar o início ou estender o fim do corte.
        antes, depois = 9, 16
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
    bons = [c for c in avaliados if c["aprovado"] and c["nota"] >= cfg["ia"]["nota_minima"]]
    bons.sort(key=lambda c: c["nota"], reverse=True)
    escolhidos = bons[: cfg["cortes"]["por_video"]]
    log.info("%d candidatos, %d aprovados, %d escolhidos.", len(candidatos), len(bons),
             len(escolhidos))

    # Registro da análise, para o painel mostrar o que foi considerado e por quê.
    (pasta / "analise.json").write_text(json.dumps({
        "duracao": meta["duracao"], "com_ia": ia.disponivel(cfg),
        "pontos": _reduzir(pontuacao),
        "sinais": {nome: _reduzir(serie) for nome, serie in usados.items()},
        "candidatos": [{
            "inicio": round(c["inicio"], 1), "fim": round(c["fim"], 1), "nota": c["nota"],
            "aprovado": c["aprovado"], "escolhido": c in escolhidos, "titulo": c["titulo"],
            "motivo": c["motivo"], "gancho": c.get("gancho", ""), "notas": c.get("notas") or {},
            "transcricao": c.get("transcricao", "")[:400],
        } for c in sorted(avaliados, key=lambda c: c["inicio"])],
    }, ensure_ascii=False), encoding="utf-8")

    # 4. Renderização.
    criados = []
    for i, c in enumerate(escolhidos):
        progresso(f"Renderizando corte {i + 1} de {len(escolhidos)}", i / len(escolhidos))
        criados.append(finalizar(c, video, meta, cfg, banco, pasta, "vod", c["falas"]))
    banco.marcar_video(meta["id"], meta["titulo"], meta["canal"],
                       "teste" if meta.get("teste") else "feito")
    if cfg["cortes"]["apagar_fonte"] and "arquivo" not in meta:
        for p in pasta.glob("fonte.*"):
            p.unlink()
    return criados
