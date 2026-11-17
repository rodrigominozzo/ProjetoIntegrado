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
             "ig_vistas INTEGER", "ig_curtidas INTEGER", "narracao TEXT", "capa TEXT",
             "capa_ms INTEGER"]
# Campanha paga por visualização e comprovante de autorização, por canal.
MIGRACOES_CANAIS = ["valor_mil REAL DEFAULT 0", "texto_obrigatorio TEXT DEFAULT ''",
                    "autorizacao TEXT DEFAULT ''"]
MAX_TENTATIVAS = 3


class Banco:
    def __init__(self, caminho: str | Path):
        self._con = sqlite3.connect(str(caminho), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._trava = threading.Lock()
        with self._trava:
            self._con.executescript(ESQUEMA)
            for tabela, colunas in (("cortes", MIGRACOES), ("canais", MIGRACOES_CANAIS)):
                for coluna in colunas:
                    try:
                        self._con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna}")
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
                   layout="", narracao="", capa="", capa_ms=None) -> int:
        cur = self._exec(
            "INSERT INTO cortes (video_id, origem, inicio, fim, nota, titulo, descricao, hashtags,"
            " arquivo, urgente, teste, gancho, notas, layout, narracao, capa, capa_ms, criado)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (video_id, origem, inicio, fim, nota, titulo, descricao, json.dumps(hashtags),
             str(arquivo), int(urgente), int(teste), gancho, json.dumps(notas or {}), layout,
             narracao, str(capa or ""), capa_ms, time.time()),
        )
        return cur.lastrowid

    def pendentes(self, plataforma: str) -> list[sqlite3.Row]:
        """Cortes ainda não publicados em 'yt' ou 'ig': urgentes e melhores notas primeiro."""
        return self._linhas(
            f"SELECT * FROM cortes WHERE teste=0 AND {plataforma}_id IS NULL"
            f" AND {plataforma}_tentativas < ?"
            # compilações são vídeos longos horizontais: só no YouTube
            + (" AND origem != 'compilacao'" if plataforma == "ig" else "") +
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
        self.apagar_arquivos(c)
        self._exec("DELETE FROM cortes WHERE id=?", (corte_id,))
        return True

    @staticmethod
    def apagar_arquivos(c) -> None:
        base = Path(c["arquivo"])
        for arq in [base, *base.parent.glob(base.stem + ".*")]:
            arq.unlink(missing_ok=True)

    def limpar_antigos(self, dias: int, plataformas: list[str]) -> int:
        """Apaga do disco os arquivos de cortes já publicados em todas as plataformas ativas
        há mais de `dias`. Os registros ficam."""
        if dias <= 0 or not plataformas:
            return 0
        limite = time.time() - dias * 86400
        feitos = 0
        for c in self._linhas("SELECT * FROM cortes WHERE teste=0"):
            alvos = [p for p in plataformas if not (p == "ig" and c["origem"] == "compilacao")]
            if alvos and all(c[f"{p}_em"] and c[f"{p}_em"] < limite for p in alvos) \
                    and Path(c["arquivo"]).exists():
                self.apagar_arquivos(c)
                feitos += 1
        return feitos

    def tem_publicados(self, video_id: str) -> bool:
        return bool(self._linhas(
            "SELECT 1 FROM cortes WHERE video_id=? AND teste=0 LIMIT 1", (video_id,)))

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

    def canal(self, canal_id: str):
        linhas = self._linhas("SELECT * FROM canais WHERE id=?", (canal_id or "",))
        return linhas[0] if linhas else None

    def campanha(self, canal_id: str, valor_mil: float, texto: str, autorizacao: str) -> None:
        self._exec("UPDATE canais SET valor_mil=?, texto_obrigatorio=?, autorizacao=? WHERE id=?",
                   (valor_mil, texto.strip(), autorizacao.strip(), canal_id))

    def vistas_por_canal(self) -> dict[str, int]:
        """Visualizações medidas (YouTube + Instagram) dos cortes de cada canal de origem."""
        linhas = self._linhas(
            "SELECT v.canal canal, SUM(COALESCE(c.yt_vistas,0)+COALESCE(c.ig_vistas,0)) n"
            " FROM cortes c JOIN videos v ON v.id=c.video_id GROUP BY v.canal")
        return {l["canal"]: l["n"] or 0 for l in linhas}

    def resumo_monetizacao(self) -> dict:
        desde = time.time() - 90 * 86400
        l = self._linhas(
            "SELECT COALESCE(SUM(CASE WHEN origem!='compilacao' AND yt_em>=? THEN yt_vistas END),0) curtas,"
            " COUNT(CASE WHEN teste=0 THEN 1 END) total,"
            " COUNT(CASE WHEN teste=0 AND narracao!='' AND narracao IS NOT NULL THEN 1 END) narrados,"
            " COUNT(CASE WHEN teste=0 AND origem='compilacao' THEN 1 END) compilacoes FROM cortes",
            (desde,))[0]
        return dict(l)

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
