"""Estado em SQLite: vídeos já processados, cortes gerados e fila de publicação."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY, titulo TEXT, canal TEXT, status TEXT, criado REAL
);
CREATE TABLE IF NOT EXISTS cortes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT, origem TEXT, inicio REAL, fim REAL, nota REAL,
    titulo TEXT, descricao TEXT, hashtags TEXT, arquivo TEXT, urgente INTEGER,
    yt_id TEXT, yt_em REAL, yt_tentativas INTEGER DEFAULT 0, yt_erro TEXT,
    ig_id TEXT, ig_em REAL, ig_tentativas INTEGER DEFAULT 0, ig_erro TEXT,
    criado REAL
);
CREATE TABLE IF NOT EXISTS canais (
    id TEXT PRIMARY KEY, nome TEXT, seguir INTEGER DEFAULT 0, criado REAL
);
CREATE TABLE IF NOT EXISTS opcoes (chave TEXT PRIMARY KEY, valor TEXT);
"""
# Colunas acrescentadas depois da primeira versão.
MIGRACOES = ["teste INTEGER DEFAULT 0", "yt_link TEXT", "ig_link TEXT", "gancho TEXT",
             "notas TEXT", "layout TEXT", "yt_vistas INTEGER", "yt_curtidas INTEGER",
             "ig_vistas INTEGER", "ig_curtidas INTEGER", "narracao TEXT"]
MAX_TENTATIVAS = 3


class Banco:
    def __init__(self, caminho: str | Path):
        self._con = sqlite3.connect(str(caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._trava = threading.Lock()
        with self._trava:
            self._con.executescript(ESQUEMA)
            for coluna in MIGRACOES:
                try:
                    self._con.execute(f"ALTER TABLE cortes ADD COLUMN {coluna}")
                except sqlite3.OperationalError:
                    pass  # já existe

    def _exec(self, sql: str, args=()):
        with self._trava:
            cur = self._con.execute(sql, args)
            self._con.commit()
            return cur

    def _linhas(self, sql: str, args=()):
        with self._trava:
            return self._con.execute(sql, args).fetchall()

    # --- vídeos ---
    def status_video(self, video_id: str) -> str | None:
        linhas = self._linhas("SELECT status FROM videos WHERE id=?", (video_id,))
        return linhas[0]["status"] if linhas else None

    def marcar_video(self, video_id: str, titulo: str, canal: str, status: str) -> None:
        self._exec(
            "INSERT INTO videos VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status",
            (video_id, titulo, canal, status, time.time()),
        )

    # --- cortes ---
    def novo_corte(self, *, video_id, origem, inicio, fim, nota, titulo, descricao,
                   hashtags, arquivo, urgente=False, teste=False, gancho="", notas=None,
                   layout="", narracao="") -> int:
        cur = self._exec(
            "INSERT INTO cortes (video_id, origem, inicio, fim, nota, titulo, descricao, hashtags,"
            " arquivo, urgente, teste, gancho, notas, layout, narracao, criado)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, origem, inicio, fim, nota, titulo, descricao, json.dumps(hashtags),
             str(arquivo), int(urgente), int(teste), gancho, json.dumps(notas or {}), layout,
             narracao, time.time()),
        )
        return cur.lastrowid

    def pendentes(self, plataforma: str) -> list[sqlite3.Row]:
        """Cortes ainda não publicados em 'yt' ou 'ig': urgentes e melhores notas primeiro."""
        return self._linhas(
            f"SELECT * FROM cortes WHERE teste=0 AND {plataforma}_id IS NULL"
            f" AND {plataforma}_tentativas < ?"
            " ORDER BY urgente DESC, nota DESC, id",
            (MAX_TENTATIVAS,),
        )

    def publicado(self, corte_id: int, plataforma: str, id_remoto: str, link: str = "") -> None:
        self._exec(
            f"UPDATE cortes SET {plataforma}_id=?, {plataforma}_link=?, {plataforma}_em=?,"
            f" {plataforma}_erro=NULL WHERE id=?",
            (id_remoto, link, time.time(), corte_id),
        )

    def corte(self, corte_id: int):
        linhas = self._linhas("SELECT * FROM cortes WHERE id=?", (corte_id,))
        return linhas[0] if linhas else None

    def todos_cortes(self) -> list[sqlite3.Row]:
        return self._linhas(
            "SELECT c.*, v.titulo AS video_titulo, v.canal AS canal FROM cortes c"
            " LEFT JOIN videos v ON v.id = c.video_id ORDER BY c.criado DESC")

    def aprovar(self, corte_id: int) -> None:
        """Tira o corte do modo teste: ele entra na fila de publicação."""
        self._exec("UPDATE cortes SET teste=0 WHERE id=?", (corte_id,))

    def tentar_de_novo(self, corte_id: int, plataforma: str) -> None:
        self._exec(f"UPDATE cortes SET {plataforma}_tentativas=0, {plataforma}_erro=NULL WHERE id=?",
                   (corte_id,))

    def remover_corte(self, corte_id: int) -> bool:
        """Apaga um corte ainda não publicado (registro e arquivo)."""
        c = self.corte(corte_id)
        if not c or c["yt_id"] or c["ig_id"]:
            return False
        Path(c["arquivo"]).unlink(missing_ok=True)
        Path(c["arquivo"]).with_suffix(".ass").unlink(missing_ok=True)
        self._exec("DELETE FROM cortes WHERE id=?", (corte_id,))
        return True

    def remover_testes(self, video_id: str) -> None:
        for c in self._linhas("SELECT id FROM cortes WHERE video_id=? AND teste=1", (video_id,)):
            self.remover_corte(c["id"])

    # --- desempenho ---
    def ids_publicados(self, plataforma: str, dias: int = 30) -> list[str]:
        linhas = self._linhas(
            f"SELECT {plataforma}_id i FROM cortes WHERE {plataforma}_id IS NOT NULL"
            f" AND {plataforma}_em >= ?", (time.time() - dias * 86400,))
        return [l["i"] for l in linhas]

    def medir(self, plataforma: str, id_remoto: str, vistas: int, curtidas: int) -> None:
        self._exec(f"UPDATE cortes SET {plataforma}_vistas=?, {plataforma}_curtidas=?"
                   f" WHERE {plataforma}_id=?", (vistas, curtidas, id_remoto))

    def cortes_medidos(self) -> list[dict]:
        """Cortes com visualizações conhecidas (soma das plataformas)."""
        linhas = self._linhas(
            "SELECT titulo, gancho, COALESCE(yt_vistas,0)+COALESCE(ig_vistas,0) vistas,"
            " COALESCE(yt_em, ig_em) publicado FROM cortes"
            " WHERE yt_vistas IS NOT NULL OR ig_vistas IS NOT NULL")
        return [dict(l) for l in linhas]

    # --- canais confiáveis e opções ---
    def canal_confiavel(self, canal_id: str, nome: str) -> None:
        if canal_id:
            self._exec("INSERT INTO canais (id, nome, criado) VALUES (?,?,?)"
                       " ON CONFLICT(id) DO UPDATE SET nome=excluded.nome",
                       (canal_id, nome, time.time()))

    def canais(self) -> list[sqlite3.Row]:
        return self._linhas("SELECT * FROM canais ORDER BY nome")

    def seguir_canal(self, canal_id: str, seguir: bool) -> None:
        self._exec("UPDATE canais SET seguir=? WHERE id=?", (int(seguir), canal_id))

    def remover_canal(self, canal_id: str) -> None:
        self._exec("DELETE FROM canais WHERE id=?", (canal_id,))

    def opcao(self, chave: str, padrao: str = "") -> str:
        linhas = self._linhas("SELECT valor FROM opcoes WHERE chave=?", (chave,))
        return linhas[0]["valor"] if linhas else padrao

    def definir_opcao(self, chave: str, valor: str) -> None:
        self._exec("INSERT INTO opcoes VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                   (chave, valor))

    def falhou(self, corte_id: int, plataforma: str, erro: str) -> None:
        self._exec(
            f"UPDATE cortes SET {plataforma}_tentativas={plataforma}_tentativas+1, {plataforma}_erro=?"
            " WHERE id=?",
            (erro[:500], corte_id),
        )

    def publicados_desde(self, plataforma: str, desde: float) -> int:
        linhas = self._linhas(
            f"SELECT COUNT(*) n FROM cortes WHERE {plataforma}_em >= ?", (desde,)
        )
        return linhas[0]["n"]

    def ultima_publicacao(self, plataforma: str) -> float:
        linhas = self._linhas(f"SELECT MAX({plataforma}_em) m FROM cortes")
        return linhas[0]["m"] or 0.0

    def resumo(self) -> dict:
        linha = self._linhas(
            "SELECT COUNT(*) total, COUNT(yt_id) yt, COUNT(ig_id) ig FROM cortes"
        )[0]
        videos = self._linhas("SELECT COUNT(*) n FROM videos")[0]["n"]
        return {"videos": videos, "cortes": linha["total"], "youtube": linha["yt"],
                "instagram": linha["ig"]}
