"""Avaliação dos candidatos com Claude: nota de viralidade, título, descrição e hashtags."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

SISTEMA = """Você é editor de um canal de cortes para YouTube Shorts e Instagram Reels.
Recebe candidatos a corte de um vídeo: quadros, transcrição, reação do chat e sinais medidos.
Para cada candidato, julgue se ele funciona sozinho, fora do contexto do vídeo completo: os
primeiros 2 segundos prendem a atenção? há um momento claro (piada, virada, revelação, reação
forte, jogada)? termina de forma satisfatória?

Dê nota de 0 a 100 para o potencial de viralização. Escreva título de até 70 caracteres, fiel
ao que acontece no trecho, sem clickbait enganoso e sem caixa alta contínua; descrição de 1 ou
2 frases; e de 3 a 6 hashtags sem o '#'. Escreva no idioma pedido.

Use ajuste_inicio e ajuste_fim (segundos, entre -5 e 5; 0 para manter) quando a transcrição
mostrar que o corte começa ou termina no meio de uma frase ou perde a preparação da piada.

Marque aprovado=false quando o trecho não tiver nada de interessante, ou quando publicá-lo
puder prejudicar o canal: nudez, violência gráfica, discurso de ódio, exposição de dados
pessoais, ou fala que fora de contexto distorce o que a pessoa quis dizer."""

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
                    "titulo": {"type": "string"},
                    "descricao": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "motivo": {"type": "string"},
                    "ajuste_inicio": {"type": "number"},
                    "ajuste_fim": {"type": "number"},
                },
                "required": ["indice", "aprovado", "nota", "titulo", "descricao", "hashtags",
                             "motivo", "ajuste_inicio", "ajuste_fim"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cortes"],
    "additionalProperties": False,
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
        })
    return resultado


def avaliar(candidatos: list[dict], contexto: dict, video: str | Path, cfg: dict) -> list[dict]:
    """Devolve os candidatos com nota e metadados. Cada candidato tem inicio, fim,
    transcricao, chat (lista de mensagens) e pontuacao."""
    if not candidatos:
        return []
    if not disponivel(cfg):
        return sem_ia(candidatos, contexto)
    import anthropic

    conteudo: list[dict] = [{
        "type": "text",
        "text": (f"Vídeo: {contexto.get('titulo', '')}\nCanal: {contexto.get('canal', '')}\n"
                 f"Idioma dos textos: {cfg['idioma']}\n"
                 f"Origem: {'live em andamento' if contexto.get('ao_vivo') else 'vídeo gravado'}"),
    }]
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
        }, ensure_ascii=False)})

    cliente = anthropic.Anthropic()
    try:
        resposta = cliente.beta.messages.create(
            model=cfg["ia"]["modelo"],
            max_tokens=16000,
            system=SISTEMA,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
            # Se o modelo principal recusar, a API reexecuta num modelo de reserva.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        log.error("ANTHROPIC_API_KEY inválida; seguindo sem IA.")
        return sem_ia(candidatos, contexto)
    except anthropic.RateLimitError:
        log.warning("Limite de uso da API atingido; seguindo sem IA neste vídeo.")
        return sem_ia(candidatos, contexto)
    except anthropic.APIStatusError as e:
        log.warning("Erro da API (%s): %s; seguindo sem IA.", e.status_code, e.message)
        return sem_ia(candidatos, contexto)
    except anthropic.APIConnectionError:
        log.warning("Sem conexão com a API; seguindo sem IA.")
        return sem_ia(candidatos, contexto)

    if resposta.stop_reason != "end_turn":
        log.warning("Resposta incompleta da IA (%s); seguindo sem IA.", resposta.stop_reason)
        return sem_ia(candidatos, contexto)
    dados = json.loads(next(b.text for b in resposta.content if b.type == "text"))
    avaliados = []
    for item in dados["cortes"]:
        if not 0 <= item["indice"] < len(candidatos):
            continue
        c = dict(candidatos[item["indice"]])
        ai = max(-5.0, min(5.0, item["ajuste_inicio"]))
        af = max(-5.0, min(5.0, item["ajuste_fim"]))
        c.update(
            aprovado=item["aprovado"], nota=float(max(0, min(100, item["nota"]))),
            titulo=item["titulo"].strip()[:90], descricao=item["descricao"].strip(),
            hashtags=[h.lstrip("#").replace(" ", "") for h in item["hashtags"]][:6],
            motivo=item["motivo"], inicio=max(0.0, c["inicio"] + ai), fim=c["fim"] + af,
        )
        if "inicio_arquivo" in c:
            c["inicio_arquivo"] = max(0.0, c["inicio_arquivo"] + ai)
            c["fim_arquivo"] = c["fim_arquivo"] + af
        avaliados.append(c)
    return avaliados
