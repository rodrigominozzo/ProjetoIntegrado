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
"""
MAX_TENTATIVAS = 3


class Banco:
    def __init__(self, caminho: str | Path):
        self._con = sqlite3.connect(str(caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._trava = threading.Lock()
        with self._trava:
            self._con.executescript(ESQUEMA)

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
                   hashtags, arquivo, urgente=False) -> int:
        cur = self._exec(
            "INSERT INTO cortes (video_id, origem, inicio, fim, nota, titulo, descricao, hashtags,"
            " arquivo, urgente, criado) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, origem, inicio, fim, nota, titulo, descricao, json.dumps(hashtags),
             str(arquivo), int(urgente), time.time()),
        )
        return cur.lastrowid

    def pendentes(self, plataforma: str) -> list[sqlite3.Row]:
        """Cortes ainda não publicados em 'yt' ou 'ig': urgentes e melhores notas primeiro."""
        return self._linhas(
            f"SELECT * FROM cortes WHERE {plataforma}_id IS NULL AND {plataforma}_tentativas < ?"
            " ORDER BY urgente DESC, nota DESC, id",
            (MAX_TENTATIVAS,),
        )

    def publicado(self, corte_id: int, plataforma: str, id_remoto: str) -> None:
        self._exec(
            f"UPDATE cortes SET {plataforma}_id=?, {plataforma}_em=?, {plataforma}_erro=NULL WHERE id=?",
            (id_remoto, time.time(), corte_id),
        )

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
