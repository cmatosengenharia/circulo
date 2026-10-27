"""Entregas de produto sem uso: os PRs de produto mergeados há 7 dias ou mais sem nenhum evento com o nome do
`evento_esperado` gravado no merge depois do `merged_at`. Uso anterior ao merge não conta: é de antes da entrega.
O evento esperado de cada entrega fica em `entrega_uso_esperado` (um por PR); o uso, em `entrega_uso` (gravado pela
rota do painel chamada, com o último instante por nome) e nos `events` do loop (kind)."""
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
USO = "CREATE TABLE IF NOT EXISTS entrega_uso (nome TEXT PRIMARY KEY, em REAL NOT NULL)"


def classificar_entregas(prs: list[dict], eventos: list[dict], agora: float) -> dict[str, list[dict]]:
    """Separa os PRs de produto (produto, evento_esperado, merged_at) com 7+ dias de merge em 'com_uso' (algum evento
    (nome, created_at) de mesmo nome estritamente depois do merge) e 'sem_uso', na ordem recebida. Pura."""
    usos: dict[str, list[float]] = {}
    for ev in eventos:
        usos.setdefault(ev["nome"], []).append(ev["created_at"])
    out: dict[str, list[dict]] = {"com_uso": [], "sem_uso": []}
    for pr in prs:
        if pr["produto"] and agora - pr["merged_at"] >= SEMANA:
            usada = any(t > pr["merged_at"] for t in usos.get(pr["evento_esperado"], ()))
            out["com_uso" if usada else "sem_uso"].append(pr)
    return out


def entregas_sem_uso(prs: list[dict], eventos: list[dict], agora: float) -> list[dict]:
    """Os PRs de produto com 7+ dias de merge e nenhum evento de mesmo nome depois do merge. Pura."""
    return classificar_entregas(prs, eventos, agora)["sem_uso"]


def registrar_esperado(conn: sqlite3.Connection, pr: int, evento: str, agora: float | None = None) -> None:
    """Grava o evento de uso esperado da entrega no merge. Idempotente: o primeiro registro do PR fica."""
    conn.execute(ESQUEMA)
    conn.execute("INSERT OR IGNORE INTO entrega_uso_esperado(pr, evento, merged_em) VALUES(?,?,?)",
                 (pr, evento, time.time() if agora is None else agora))


def nome_uso(caminho: str) -> str:
    """O nome de uso de uma rota do painel: `endpoint:<caminho>` para /api, `tela:<caminho>` para as páginas."""
    return ("endpoint:" if caminho.startswith("/api/") else "tela:") + caminho


def registrar_uso(conn: sqlite3.Connection, nome: str, agora: float | None = None) -> None:
    """Grava o uso real (nome, instante) só se alguma entrega o espera; uma linha por nome, com o último uso."""
    conn.execute(ESQUEMA)
    conn.execute(USO)
    conn.execute("INSERT INTO entrega_uso(nome, em) SELECT ?, ? WHERE EXISTS "
                 "(SELECT 1 FROM entrega_uso_esperado WHERE evento = ?) "
                 "ON CONFLICT(nome) DO UPDATE SET em = MAX(em, excluded.em)",
                 (nome, time.time() if agora is None else agora, nome))


def classificar(conn: sqlite3.Connection, agora: float) -> dict[str, list[dict]]:
    """As entregas gravadas há 7+ dias, por número de PR, separadas em 'com_uso' e 'sem_uso' (uso depois do merge)."""
    conn.execute(ESQUEMA)
    conn.execute(USO)
    prs = [{"number": pr, "produto": True, "evento_esperado": evento, "merged_at": em} for pr, evento, em in
           conn.execute("SELECT pr, evento, merged_em FROM entrega_uso_esperado ORDER BY pr")]
    eventos = [{"nome": kind, "created_at": em} for kind, em in conn.execute(
        "SELECT kind, created_at FROM events WHERE kind IN (SELECT evento FROM entrega_uso_esperado) "
        "UNION ALL SELECT nome, em FROM entrega_uso")]
    return classificar_entregas(prs, eventos, agora)


def listar_sem_uso(conn: sqlite3.Connection, agora: float) -> list[dict]:
    """As entregas gravadas há 7+ dias sem evento de uso depois do merge, por número de PR."""
    return classificar(conn, agora)["sem_uso"]


def resumo_7d(classes: dict[str, list[dict]]) -> dict:
    """Os números de PR com e sem uso e o total de entregas maduras; toda madura cai em uma das duas listas."""
    com, sem = ([e["number"] for e in classes[k]] for k in ("com_uso", "sem_uso"))
    return {"com_uso": com, "sem_uso": sem, "maduras": len(com) + len(sem)}
