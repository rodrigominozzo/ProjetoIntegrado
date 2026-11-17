"""Bases de conhecimento: arquivos .md que a IA recebe quando o assunto do vídeo combina.

Cada arquivo em `conhecimento/` começa com um cabeçalho simples:

    palavras: gta 6, gta vi, vice city      (assuntos que ativam a base)
    sempre: sim                             (opcional: entra em toda avaliação)
    ---
    ...texto livre...
"""
from __future__ import annotations

import re
from pathlib import Path


def pasta(cfg: dict) -> Path:
    p = Path(cfg.get("conhecimento", {}).get("pasta", "conhecimento"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def ler(arquivo: Path) -> dict:
    bruto = arquivo.read_text(encoding="utf-8")
    cabecalho, _, corpo = bruto.partition("\n---\n")
    if not corpo:  # arquivo sem cabeçalho: só texto, nunca ativado sozinho
        cabecalho, corpo = "", bruto
    palavras = re.search(r"^palavras:\s*(.*)$", cabecalho, re.M | re.I)
    sempre = re.search(r"^sempre:\s*(sim|true|1)\s*$", cabecalho, re.M | re.I)
    return {"nome": arquivo.stem, "sempre": bool(sempre), "texto": corpo.strip(), "bruto": bruto,
            "palavras": [p.strip().lower() for p in palavras[1].split(",") if p.strip()]
            if palavras else []}


def listar(cfg: dict) -> list[dict]:
    return [ler(a) for a in sorted(pasta(cfg).glob("*.md"))]


def selecionar(texto: str, cfg: dict) -> str:
    """Texto das bases que se aplicam a este vídeo, pronto para entrar no pedido à IA."""
    alvo = texto.lower()
    partes = []
    for base in listar(cfg):
        casa = any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", alvo) for p in base["palavras"])
        if base["texto"] and (base["sempre"] or casa):
            partes.append(f"## Base de conhecimento: {base['nome']}\n{base['texto']}")
    return "\n\n".join(partes)


def salvar(cfg: dict, nome: str, conteudo: str) -> None:
    nome = re.sub(r"[^\w-]+", "-", nome.strip().lower()).strip("-")
    if not nome:
        raise ValueError("Dê um nome à base de conhecimento.")
    (pasta(cfg) / f"{nome}.md").write_text(conteudo, encoding="utf-8")


def remover(cfg: dict, nome: str) -> None:
    arquivo = pasta(cfg) / f"{re.sub(r'[^\w-]+', '-', nome)}.md"
    arquivo.unlink(missing_ok=True)
