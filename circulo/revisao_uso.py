"""Pedido de revisão por entrega de produto sem uso: um por PR, para sempre. A chave é `pr_numero UNIQUE` e a abertura
é `INSERT ... ON CONFLICT DO NOTHING`, então repetição (seguida ou em paralelo, de qualquer conexão) não duplica e
pedido fechado não reabre: a chave não expira nem é podada. O destino (usar, ajustar ou remover) segue a regra da
chave de idempotência: o primeiro fica, e uma repetição com destino diferente vira divergência registrada."""
from __future__ import annotations

import sqlite3
import time

from .uso_entregas import listar_sem_uso

DESTINOS = ("usar", "ajustar", "remover")
ESQUEMA = """
CREATE TABLE IF NOT EXISTS revisao_uso (
  pr_numero INTEGER NOT NULL UNIQUE,
  evento TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto', 'fechado')),
  destino TEXT CHECK (destino IN ('usar', 'ajustar', 'remover')),
  aberto_em REAL NOT NULL,
  fechado_em REAL
)
"""
DIVERGENCIA = """
CREATE TABLE IF NOT EXISTS revisao_uso_divergencia (
  pr_numero INTEGER NOT NULL,
  destino TEXT NOT NULL,
  destino_novo TEXT NOT NULL,
  em REAL NOT NULL
)
"""


def abrir_pedidos_revisao_uso(conn: sqlite3.Connection, agora: float | None = None) -> list[int]:
    """Abre um pedido para cada entrega de produto com 7+ dias e sem evento de uso que ainda não tem pedido (aberto ou
    fechado). Devolve os PRs abertos por esta chamada."""
    agora = time.time() if agora is None else agora
    conn.execute(ESQUEMA)
    abertos = []
    for e in listar_sem_uso(conn, agora):
        cur = conn.execute("INSERT INTO revisao_uso(pr_numero, evento, aberto_em) VALUES(?,?,?) "
                           "ON CONFLICT(pr_numero) DO NOTHING", (e["number"], e["evento_esperado"], agora))
        if cur.rowcount:
            abertos.append(e["number"])
    return abertos


def decidir(conn: sqlite3.Connection, pr: int, destino: str, agora: float | None = None) -> str:
    """Grava o destino do pedido do PR se ainda não há um; destino diferente do gravado vira divergência e não troca.
    Devolve o destino que vale."""
    if destino not in DESTINOS:
        raise ValueError(f"destino {destino!r} fora de {DESTINOS}")
    conn.execute(ESQUEMA)
    conn.execute(DIVERGENCIA)
    conn.execute("UPDATE revisao_uso SET destino=? WHERE pr_numero=? AND destino IS NULL", (destino, pr))
    linha = conn.execute("SELECT destino FROM revisao_uso WHERE pr_numero=?", (pr,)).fetchone()
    if linha is None:
        raise KeyError(f"PR #{pr} sem pedido de revisão de uso")
    if linha[0] != destino:
        conn.execute("INSERT INTO revisao_uso_divergencia(pr_numero, destino, destino_novo, em) VALUES(?,?,?,?)",
                     (pr, linha[0], destino, time.time() if agora is None else agora))
    return linha[0]


def fechar(conn: sqlite3.Connection, pr: int, agora: float | None = None) -> None:
    """Fecha o pedido do PR; a linha fica, e é ela que impede a reabertura."""
    conn.execute(ESQUEMA)
    conn.execute("UPDATE revisao_uso SET status='fechado', fechado_em=? WHERE pr_numero=? AND status='aberto'",
                 (time.time() if agora is None else agora, pr))
