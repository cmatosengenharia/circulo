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
  fechado_em REAL,
  item_id INTEGER
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


def _esquema(conn: sqlite3.Connection) -> None:
    conn.execute(ESQUEMA)
    if "item_id" not in {r[1] for r in conn.execute("PRAGMA table_info(revisao_uso)")}:
        conn.execute("ALTER TABLE revisao_uso ADD COLUMN item_id INTEGER")


def titulo(pr: int, evento: str) -> str:
    return f"Revisar a entrega #{pr} sem uso após 7 dias: divulgar ou remover (evento esperado: {evento})"


def cobrar_no_roteiro(store, pergunta_id: int, agora: float | None = None) -> list[int]:
    """Cada pedido aberto ainda sem item vira um item de revisão no roteiro, preso à pergunta do PM (lição #15). O
    `item_id` gravado no pedido é a marca de já cobrada: a chave é o PR (não o evento esperado), então o item resolvido
    não volta e duas entregas com o mesmo evento têm um item cada. O pedido é reservado (item_id=0) antes de gravar o
    item, para que duas execuções em paralelo não cobrem o mesmo PR duas vezes. Devolve os itens criados."""
    from .planejador import exigir_pergunta, gravar_item
    pid = exigir_pergunta(store, pergunta_id)
    abrir_pedidos_revisao_uso(store.db, agora)
    novos = []
    for pr, evento in store.db.execute("SELECT pr_numero, evento FROM revisao_uso WHERE status='aberto' "
                                       "AND item_id IS NULL ORDER BY pr_numero").fetchall():
        if not store.db.execute("UPDATE revisao_uso SET item_id=0 WHERE pr_numero=? AND item_id IS NULL",
                                (pr,)).rowcount:
            continue
        try:
            rid = gravar_item(store, pid, titulo(pr, evento),
                              f"O PR #{pr} foi mergeado há 7+ dias e nenhum evento '{evento}' foi registrado depois: "
                              "divulgar a entrega ou removê-la.", f"entrega sem uso: PR #{pr}, evento esperado {evento}")
        except Exception:
            store.db.execute("UPDATE revisao_uso SET item_id=NULL WHERE pr_numero=?", (pr,))
            raise
        store.db.execute("UPDATE revisao_uso SET item_id=? WHERE pr_numero=?", (rid, pr))
        novos.append(rid)
    return novos


def cobrar_no_giro(store, agora: float | None = None) -> list[int]:
    """O giro abre os pedidos e, se o conselho já tem pergunta do PM, cobra cada um no roteiro (uma vez por PR)."""
    abrir_pedidos_revisao_uso(store.db, agora)
    r = store.one("SELECT id FROM perguntas WHERE persona='pm' ORDER BY id DESC LIMIT 1")
    return cobrar_no_roteiro(store, r["id"], agora) if r else []


def abrir_pedidos_revisao_uso(conn: sqlite3.Connection, agora: float | None = None) -> list[int]:
    """Abre um pedido para cada entrega de produto com 7+ dias e sem evento de uso que ainda não tem pedido (aberto ou
    fechado). Devolve os PRs abertos por esta chamada."""
    agora = time.time() if agora is None else agora
    _esquema(conn)
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
