"""Entregas de produto sem uso: os PRs de produto mergeados há 7 dias ou mais sem nenhum evento com o nome do
`evento_esperado` gravado no merge depois do `merged_at`. Uso anterior ao merge não conta: é de antes da entrega.
O evento esperado de cada entrega fica em `entrega_uso_esperado` (um por PR); o uso, nos `events` do loop (kind)."""
from __future__ import annotations

import sqlite3
import time

from .norte import SEMANA

ESQUEMA = """
CREATE TABLE IF NOT EXISTS entrega_uso_esperado (
  pr INTEGER PRIMARY KEY,
  evento TEXT NOT NULL,
  merged_em REAL NOT NULL
)
"""


def entregas_sem_uso(prs: list[dict], eventos: list[dict], agora: float) -> list[dict]:
    """Os PRs de produto (produto, evento_esperado, merged_at) com 7+ dias de merge e nenhum evento (nome, created_at)
    de mesmo nome estritamente depois do merge, na ordem recebida. Pura."""
    usos: dict[str, list[float]] = {}
    for ev in eventos:
        usos.setdefault(ev["nome"], []).append(ev["created_at"])
    return [pr for pr in prs
            if pr["produto"] and agora - pr["merged_at"] >= SEMANA
            and not any(t > pr["merged_at"] for t in usos.get(pr["evento_esperado"], ()))]


def registrar_esperado(conn: sqlite3.Connection, pr: int, evento: str, agora: float | None = None) -> None:
    """Grava o evento de uso esperado da entrega no merge. Idempotente: o primeiro registro do PR fica."""
    conn.execute(ESQUEMA)
    conn.execute("INSERT OR IGNORE INTO entrega_uso_esperado(pr, evento, merged_em) VALUES(?,?,?)",
                 (pr, evento, time.time() if agora is None else agora))


def listar_sem_uso(conn: sqlite3.Connection, agora: float) -> list[dict]:
    """As entregas gravadas há 7+ dias sem evento de uso depois do merge, por número de PR."""
    conn.execute(ESQUEMA)
    prs = [{"number": pr, "produto": True, "evento_esperado": evento, "merged_at": em} for pr, evento, em in
           conn.execute("SELECT pr, evento, merged_em FROM entrega_uso_esperado ORDER BY pr")]
    eventos = [{"nome": kind, "created_at": em} for kind, em in conn.execute(
        "SELECT kind, created_at FROM events WHERE kind IN (SELECT evento FROM entrega_uso_esperado)")]
    return entregas_sem_uso(prs, eventos, agora)
