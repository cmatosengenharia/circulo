"""Memória da fábrica: SQLite, só a biblioteca padrão. Cartões, passos, achados, eventos (para o painel) e chave-valor."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cartoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  titulo TEXT NOT NULL, pedido TEXT NOT NULL, origem TEXT NOT NULL,
  estado TEXT NOT NULL, dados TEXT NOT NULL DEFAULT '{}',
  devolucoes INTEGER NOT NULL DEFAULT 0, criado_em REAL NOT NULL, atualizado_em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS passos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cartao INTEGER NOT NULL, papel TEXT NOT NULL,
  de_estado TEXT NOT NULL, para_estado TEXT NOT NULL, mensagem TEXT NOT NULL, evidencias TEXT NOT NULL,
  duracao_s REAL NOT NULL, em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS achados (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cartao INTEGER, papel TEXT NOT NULL, assunto TEXT NOT NULL,
  texto TEXT NOT NULL, base TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'aberto', vezes INTEGER NOT NULL DEFAULT 1,
  criado_em REAL NOT NULL, atualizado_em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eventos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, cartao INTEGER, de_papel TEXT, para_papel TEXT,
  texto TEXT NOT NULL, dados TEXT NOT NULL DEFAULT '{}', em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kv (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
"""


class Estado:
    def __init__(self, caminho: str | Path):
        self.caminho = str(caminho)
        self.db = sqlite3.connect(self.caminho, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ---------- genérico
    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def um(self, sql: str, args=()) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            return self.db.execute(sql, args).lastrowid or 0

    def get(self, chave: str, padrao: Any = None) -> Any:
        r = self.um("SELECT valor FROM kv WHERE chave=?", (chave,))
        return json.loads(r["valor"]) if r else padrao

    def set(self, chave: str, valor: Any) -> None:
        self.x("INSERT INTO kv(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
               (chave, json.dumps(valor, ensure_ascii=False, default=str)))

    # ---------- cartões
    def novo_cartao(self, titulo: str, pedido: str, origem: str = "humano") -> int:
        agora = time.time()
        cid = self.x("INSERT INTO cartoes(titulo,pedido,origem,estado,criado_em,atualizado_em) VALUES(?,?,?,'novo',?,?)",
                     (titulo[:160], pedido, origem, agora, agora))
        self.evento("cartao", cid, "humano" if origem == "humano" else "release", "po", f"Pedido novo: {titulo[:120]}")
        return cid

    def cartao(self, cid: int) -> dict | None:
        r = self.um("SELECT * FROM cartoes WHERE id=?", (cid,))
        if not r:
            return None
        d = dict(r)
        d["dados"] = json.loads(d["dados"] or "{}")
        return d

    def em_andamento(self) -> dict | None:
        """O cartão em voo (um só por vez: confiança antes de paralelismo)."""
        r = self.um("SELECT id FROM cartoes WHERE estado NOT IN ('novo','concluido','bloqueado','cancelado') ORDER BY atualizado_em LIMIT 1")
        return self.cartao(r["id"]) if r else None

    def proximo_novo(self) -> dict | None:
        r = self.um("SELECT id FROM cartoes WHERE estado='novo' ORDER BY CASE origem WHEN 'humano' THEN 0 ELSE 1 END, id LIMIT 1")
        return self.cartao(r["id"]) if r else None

    def mover(self, cid: int, para: str, dados: dict | None = None, devolucao: bool = False) -> None:
        c = self.cartao(cid) or {"dados": {}, "devolucoes": 0}
        novos = {**c["dados"], **(dados or {})}
        dev = c["devolucoes"] + 1 if devolucao else (0 if para not in ("bloqueado",) else c["devolucoes"])
        self.x("UPDATE cartoes SET estado=?, dados=?, devolucoes=?, atualizado_em=? WHERE id=?",
               (para, json.dumps(novos, ensure_ascii=False, default=str), dev, time.time(), cid))

    def passo(self, cid: int, papel: str, de: str, para: str, mensagem: str, evidencias: list, duracao: float) -> int:
        return self.x("INSERT INTO passos(cartao,papel,de_estado,para_estado,mensagem,evidencias,duracao_s,em) VALUES(?,?,?,?,?,?,?,?)",
                      (cid, papel, de, para, mensagem[:1000], json.dumps([e.__dict__ for e in evidencias], ensure_ascii=False, default=str)[:8000],
                       round(duracao, 3), time.time()))

    def passos(self, cid: int) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM passos WHERE cartao=? ORDER BY id", (cid,)):
            d = dict(r)
            d["evidencias"] = json.loads(d["evidencias"] or "[]")
            out.append(d)
        return out

    # ---------- achados (o documento que o humano lê de vez em quando)
    def achado(self, papel: str, assunto: str, texto: str, base: str = "medido", cartao: int | None = None) -> int:
        agora = time.time()
        r = self.um("SELECT id FROM achados WHERE assunto=? AND status='aberto'", (assunto,))
        if r:
            self.x("UPDATE achados SET vezes=vezes+1, texto=?, atualizado_em=?, cartao=COALESCE(?, cartao) WHERE id=?", (texto[:1000], agora, cartao, r["id"]))
            return r["id"]
        return self.x("INSERT INTO achados(cartao,papel,assunto,texto,base,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?)",
                      (cartao, papel, assunto[:160], texto[:1000], base, agora, agora))

    def achados_abertos(self) -> list[dict]:
        return [dict(r) for r in self.q("SELECT * FROM achados WHERE status='aberto' ORDER BY vezes DESC, atualizado_em DESC")]

    # ---------- eventos (o painel assiste)
    def evento(self, tipo: str, cartao: int | None, de: str | None, para: str | None, texto: str, dados: dict | None = None) -> int:
        return self.x("INSERT INTO eventos(tipo,cartao,de_papel,para_papel,texto,dados,em) VALUES(?,?,?,?,?,?,?)",
                      (tipo, cartao, de, para, texto[:600], json.dumps(dados or {}, ensure_ascii=False, default=str)[:4000], time.time()))

    def eventos_desde(self, ultimo_id: int, limite: int = 200) -> list[dict]:
        out = []
        for r in self.q("SELECT * FROM eventos WHERE id>? ORDER BY id LIMIT ?", (ultimo_id, limite)):
            d = dict(r)
            d["dados"] = json.loads(d["dados"] or "{}")
            out.append(d)
        return out

    def ultimo_evento(self) -> int:
        r = self.um("SELECT MAX(id) m FROM eventos")
        return int(r["m"] or 0) if r else 0
