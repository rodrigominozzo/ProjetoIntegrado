"""Avaliação dos candidatos com Claude, com um modelo para cada papel:

  triagem  (Haiku)  — lê só texto de muitos candidatos e descarta os fracos; rápido e barato
  ao_vivo  (Sonnet) — avalia o pico de uma live com imagens; equilíbrio entre rapidez e critério
  final    (Opus)   — julgamento criativo dos finalistas: nota, gancho, título e direção de edição
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
from pathlib import Path

from . import conhecimento

log = logging.getLogger(__name__)

SISTEMA = """Você é editor de um canal de cortes para YouTube Shorts e Instagram Reels.
Recebe candidatos a corte de um vídeo: quadros, transcrição, reação do chat e sinais medidos.
Para cada candidato, julgue se ele funciona sozinho, fora do contexto do vídeo completo: os
primeiros 2 segundos prendem a atenção? há um momento claro (piada, virada, revelação, reação
forte, jogada)? termina de forma satisfatória?

Avalie quatro critérios, cada um de 0 a 100:
- gancho: os 3 primeiros segundos fazem a pessoa parar de rolar a tela?
- emocao: provoca riso, espanto, tensão ou identificação?
- clareza: dá para entender sem ter visto o resto do vídeo?
- compartilhavel: alguém mandaria isso para um amigo ou comentaria?
A nota geral (0 a 100) é o seu julgamento do potencial de viralização, não a média.

Escreva, no idioma pedido:
- gancho_texto: frase de até 45 caracteres que fica fixa no topo do vídeo. Deve abrir uma
  curiosidade sobre o que vai acontecer sem entregar o desfecho, e ser verdadeira. Pense em
  três opções e devolva a mais forte.
- titulo: até 70 caracteres, fiel ao trecho, com as palavras que alguém buscaria (nome da
  pessoa, jogo, assunto); sem clickbait enganoso e sem caixa alta contínua.
- descricao: 1 ou 2 frases com contexto e, no fim, um único convite à ação (por exemplo,
  seguir o canal). Um só: vários pedidos juntos fazem a pessoa ignorar todos.
- hashtags: de 3 a 6, sem o '#', misturando o tema específico e o geral.
- narracao: uma frase de até 14 palavras, que um narrador do canal diz nos primeiros
  segundos por cima do vídeo. É a contribuição própria do canal: dê o contexto que falta
  a quem não viu o resto e um olhar seu sobre por que o momento é notável. Não descreva o
  que já se vê, não repita o gancho, não entregue o desfecho. Se o trecho abre com uma
  fala que não pode ser coberta, ou não há nada útil a acrescentar, devolva vazio.

Direção de edição (o programa monta o vídeo a partir destas três respostas):
- momento_chave: em que segundo, contado do início atual do candidato, acontece o ápice
  (a reação, a jogada, a frase de efeito). É ali que a edição fecha no rosto ou dá zoom.
- abrir_com_pico: true quando os primeiros segundos são mornos mas o ápice é forte o
  bastante para abrir o vídeo com 1,5 s dele antes de voltar ao começo. Use com parcimônia:
  se o trecho já começa bem, ou se mostrar o ápice estraga a surpresa, deixe false.
- palavras_chave: até 4 palavras da transcrição que carregam o sentido ou a emoção do
  trecho, para destacar na legenda. Copie-as exatamente como aparecem.

Use ajuste_inicio e ajuste_fim (em segundos; 0 para manter; negativos adiantam) para que o
corte comece no gancho, sem enrolação antes, e termine logo depois do desfecho. Os limites
de cada ajuste vêm indicados em cada candidato. Prefira começar tarde a começar cedo.

Marque aprovado=false quando o trecho não tiver nada de interessante, ou quando publicá-lo
puder prejudicar o canal: nudez, violência gráfica real, discurso de ódio, exposição de
dados pessoais, ou fala que fora de contexto distorce o que a pessoa quis dizer."""

SISTEMA_TRIAGEM = """Você faz a primeira triagem de candidatos a corte de vídeo para Shorts e
Reels, lendo apenas a transcrição e a reação do chat de cada um. Dê a cada candidato uma nota
de 0 a 100 para a chance de render um corte que prenda a atenção sozinho, fora de contexto.
Seja rápido e criterioso: uma etapa posterior, com imagens, fará o julgamento final dos
melhores. Candidatos sem transcrição podem ser bons (a graça pode estar na imagem): nesses,
guie-se pelo chat e pela pontuação dos sinais, e na dúvida dê nota intermediária."""

CRITERIOS = ("gancho", "emocao", "clareza", "compartilhavel")

ESQUEMA = {
    "type": "object",
    "properties": {
        "cortes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "indice": {"type": "integer"},
                    "aprovado": {"type": "boolean"},
                    "nota": {"type": "integer"},
                    "notas": {
                        "type": "object",
                        "properties": {k: {"type": "integer"} for k in CRITERIOS},
                        "required": list(CRITERIOS), "additionalProperties": False,
                    },
                    "gancho_texto": {"type": "string"},
                    "titulo": {"type": "string"},
                    "descricao": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "narracao": {"type": "string"},
                    "motivo": {"type": "string"},
                    "momento_chave": {"type": "number"},
                    "abrir_com_pico": {"type": "boolean"},
                    "palavras_chave": {"type": "array", "items": {"type": "string"}},
                    "ajuste_inicio": {"type": "number"},
                    "ajuste_fim": {"type": "number"},
                },
                "required": ["indice", "aprovado", "nota", "notas", "gancho_texto", "titulo",
                             "descricao", "hashtags", "narracao", "motivo", "momento_chave",
                             "abrir_com_pico", "palavras_chave", "ajuste_inicio", "ajuste_fim"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cortes"],
    "additionalProperties": False,
}

ESQUEMA_TRIAGEM = {
    "type": "object",
    "properties": {"notas": {"type": "array", "items": {
        "type": "object",
        "properties": {"indice": {"type": "integer"}, "nota": {"type": "integer"}},
        "required": ["indice", "nota"], "additionalProperties": False}}},
    "required": ["notas"], "additionalProperties": False,
}


def disponivel(cfg: dict) -> bool:
    return bool(cfg["ia"]["ativa"] and os.environ.get("ANTHROPIC_API_KEY"))


def quadros(video: str | Path, inicio: float, fim: float, quantidade: int) -> list[bytes]:
    """Quadros JPEG pequenos, espaçados ao longo do trecho."""
    imagens = []
    for i in range(quantidade):
        t = inicio + (fim - inicio) * (i + 0.5) / quantidade
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=512:-2", "-q:v", "6", "-f", "image2pipe", "-c:v", "mjpeg", "-"],
            capture_output=True,
        )
        if r.returncode == 0 and r.stdout:
            imagens.append(r.stdout)
    return imagens


def sem_ia(candidatos: list[dict], contexto: dict) -> list[dict]:
    """Metadados simples quando a IA está desligada ou falha: mantém a ordem dos sinais."""
    base = re.sub(r"\s+", " ", contexto.get("titulo", "")).strip() or "Melhor momento"
    resultado = []
    for i, c in enumerate(candidatos):
        resultado.append({
            **c, "aprovado": True, "nota": round(min(99.0, 50 + 25 * c.get("pontuacao", 0)), 1),
            "titulo": base[:70], "descricao": f"Momento {i + 1} de: {base}",
            "hashtags": ["shorts", "cortes", "viral"], "motivo": "sem IA: ordenado pelos sinais",
            "gancho": "", "notas": {}, "momento": None, "abrir_com_pico": False,
            "palavras_chave": [], "narracao": "",
        })
    return resultado


def _pedir(modelo: str, sistema: str, conteudo: list[dict], esquema: dict) -> dict | None:
    """Uma chamada com saída estruturada. Devolve o JSON, ou None se não deu certo."""
    import anthropic

    extras = {}
    if "haiku" not in modelo:
        # Se o modelo recusar, a API reexecuta num modelo de reserva (o Haiku não tem isso).
        extras = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        resposta = anthropic.Anthropic().beta.messages.create(
            model=modelo, max_tokens=16000, system=sistema,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
            **extras,
        )
    except anthropic.AuthenticationError:
        log.error("ANTHROPIC_API_KEY inválida.")
        return None
    except anthropic.RateLimitError:
        log.warning("Limite de uso da API atingido (%s).", modelo)
        return None
    except anthropic.APIStatusError as e:
        log.warning("Erro da API em %s (%s): %s", modelo, e.status_code, e.message)
        return None
    except anthropic.APIConnectionError:
        log.warning("Sem conexão com a API.")
        return None
    if resposta.stop_reason != "end_turn":
        log.warning("Resposta incompleta de %s (%s).", modelo, resposta.stop_reason)
        return None
    return json.loads(next(b.text for b in resposta.content if b.type == "text"))


def _cabecalho(contexto: dict, cfg: dict) -> str:
    return (f"Vídeo: {contexto.get('titulo', '')}\nCanal: {contexto.get('canal', '')}\n"
            f"Idioma dos textos: {cfg['idioma']}\n"
            f"Origem: {'live em andamento' if contexto.get('ao_vivo') else 'vídeo gravado'}\n"
            f"Duração permitida do corte: {cfg['cortes']['duracao_min']} a "
            f"{cfg['cortes']['duracao_max']} segundos")


def triar(candidatos: list[dict], contexto: dict, cfg: dict, manter: int) -> list[dict]:
    """Primeira peneira com o modelo rápido, só com texto. Na dúvida ou em falha, mantém tudo."""
    if len(candidatos) <= manter or not disponivel(cfg):
        return candidatos
    conteudo = [{"type": "text", "text": _cabecalho(contexto, cfg)}]
    for i, c in enumerate(candidatos):
        conteudo.append({"type": "text", "text": f"Candidato {i}: " + json.dumps({
            "transcricao": c.get("transcricao") or "(sem transcrição)",
            "chat": (c.get("chat") or [])[:12],
            "pontuacao_sinais": round(c.get("pontuacao", 0), 2)}, ensure_ascii=False)})
    dados = _pedir(cfg["ia"]["modelos"]["triagem"], SISTEMA_TRIAGEM, conteudo, ESQUEMA_TRIAGEM)
    if not dados:
        return candidatos
    notas = {n["indice"]: n["nota"] for n in dados["notas"] if 0 <= n["indice"] < len(candidatos)}
    ordem = sorted(range(len(candidatos)), key=lambda i: notas.get(i, 50), reverse=True)
    return [candidatos[i] for i in sorted(ordem[:manter])]


def avaliar(candidatos: list[dict], contexto: dict, video: str | Path, cfg: dict) -> list[dict]:
    """Devolve os candidatos com nota, metadados e direção de edição. Cada candidato tem
    inicio, fim, transcricao, chat (lista de mensagens) e pontuacao."""
    if not candidatos:
        return []
    if not disponivel(cfg):
        return sem_ia(candidatos, contexto)

    conteudo: list[dict] = [{"type": "text", "text": _cabecalho(contexto, cfg)}]
    textos = " ".join([contexto.get("titulo", ""), contexto.get("canal", "")]
                      + [c.get("transcricao") or "" for c in candidatos])
    base = conhecimento.selecionar(textos, cfg)
    if base:
        conteudo.append({"type": "text", "text": base})
    if contexto.get("referencias"):
        conteudo.append({"type": "text", "text": contexto["referencias"]})
    for i, c in enumerate(candidatos):
        conteudo.append({"type": "text", "text": f"--- Candidato {i} ({c['inicio']:.0f}s a {c['fim']:.0f}s) ---"})
        for img in quadros(video, c.get("inicio_arquivo", c["inicio"]),
                           c.get("fim_arquivo", c["fim"]), cfg["ia"]["quadros"]):
            conteudo.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(img).decode()}})
        conteudo.append({"type": "text", "text": json.dumps({
            "transcricao": c.get("transcricao") or "(sem transcrição)",
            "chat": c.get("chat") or [],
            "pontuacao_sinais": round(c.get("pontuacao", 0), 2),
            "duracao_atual": round(c["fim"] - c["inicio"], 1),
            "limites_ajuste_inicio": [-c.get("folga_inicio", 8), 5],
            "limites_ajuste_fim": [-5, c.get("folga_fim", 15)],
        }, ensure_ascii=False)})

    papel = "ao_vivo" if contexto.get("ao_vivo") else "final"
    dados = _pedir(cfg["ia"]["modelos"][papel], SISTEMA, conteudo, ESQUEMA)
    if not dados:
        log.warning("Seguindo sem IA neste vídeo.")
        return sem_ia(candidatos, contexto)
    avaliados = []
    for item in dados["cortes"]:
        if not 0 <= item["indice"] < len(candidatos):
            continue
        c = dict(candidatos[item["indice"]])
        ai = max(-float(c.get("folga_inicio", 8)), min(5.0, item["ajuste_inicio"]))
        af = max(-5.0, min(float(c.get("folga_fim", 15)), item["ajuste_fim"]))
        # Mantém a duração dentro da faixa configurada, mexendo só no fim.
        dur = (c["fim"] + af) - (c["inicio"] + ai)
        dur_ok = max(cfg["cortes"]["duracao_min"], min(cfg["cortes"]["duracao_max"], dur))
        af = min(af + (dur_ok - dur), float(c.get("folga_fim", 15)))
        # momento_chave vem contado do início original; guarda como deslocamento no corte final.
        momento = max(0.0, min(item["momento_chave"] - ai, dur_ok))
        c.update(
            aprovado=item["aprovado"], nota=float(max(0, min(100, item["nota"]))),
            titulo=item["titulo"].strip()[:90], descricao=item["descricao"].strip(),
            hashtags=[h.lstrip("#").replace(" ", "") for h in item["hashtags"]][:6],
            gancho=item["gancho_texto"].strip()[:60],
            notas={k: max(0, min(100, item["notas"][k])) for k in CRITERIOS},
            momento=momento, abrir_com_pico=item["abrir_com_pico"],
            palavras_chave=item["palavras_chave"][:4],
            narracao=" ".join(item["narracao"].split()[:18]),
            motivo=item["motivo"], inicio=max(0.0, c["inicio"] + ai), fim=c["fim"] + af,
        )
        if "inicio_arquivo" in c:
            c["inicio_arquivo"] = max(0.0, c["inicio_arquivo"] + ai)
            c["fim_arquivo"] = c["fim_arquivo"] + af
        avaliados.append(c)
    return avaliados
