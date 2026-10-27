"""Pedido ao humano quando a pasta de extratos não dá lançamentos: o código de ingestão existe, falta o arquivo.

A cada giro, `girar` passa a pasta (`lancamentos_pasta.ingerir_pasta`) e lê o diagnóstico. Com a pasta inexistente
ou vazia por GIROS giros seguidos, abre um pedido com a causa, o caminho da pasta e o formato aceito. Um índice único
parcial deixa no máximo 1 pedido aberto por causa (como o Alertmanager agrupa por rótulo); quando a causa some
(extrato solto, pasta criada), o pedido fecha sozinho. Os abertos aparecem em "Precisa de você" (`aprovacoes`).
Todo giro grava a causa da rodada em kv `ingestao_causas` (as últimas RODADAS e a dominante entre elas)."""
from __future__ import annotations

import time
from pathlib import Path

from .lancamentos_pasta import FORMATOS, _extratos, ingerir_pasta
from .state import Store

GIROS = 3
RODADAS = 10           # giros guardados em kv `ingestao_causas`; a mais frequente explica lancamentos=0
CAUSAS = {"pasta_inexistente": "a pasta de extratos não existe", "vazia": "a pasta de extratos está vazia"}
ESQUEMA = """
CREATE TABLE IF NOT EXISTS pedidos_ingestao (
  id INTEGER PRIMARY KEY,
  causa TEXT NOT NULL,
  pasta TEXT NOT NULL,
  mensagem TEXT NOT NULL,
  aberto_em REAL NOT NULL,
  fechado_em REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS pedidos_ingestao_aberto ON pedidos_ingestao(causa) WHERE fechado_em IS NULL;
"""


def _esquema(store: Store) -> None:
    with store.lock:
        store.db.executescript(ESQUEMA)


def mensagem(causa: str, pasta: Path) -> str:
    formatos = ", ".join(sorted(FORMATOS))
    return (f"Sem lançamentos: {CAUSAS[causa]} há {GIROS}+ giros. Solte o extrato do banco ({formatos}) em {pasta} "
            "(crie a pasta se não existir); o próximo giro importa e este pedido fecha sozinho.")


def causa_da_rodada(motivo: str, pendentes: int, novos: int) -> str:
    """O `diagnosticar` olha a pasta; a rodada separa o que cai em `ok(n)`: importou, só duplicata ou nada novo."""
    if novos:
        return "importados"
    if motivo.startswith("ok"):
        return "so_duplicata" if pendentes else "sem_extrato_novo"
    return motivo.split("(")[0]


def _registrar(store: Store, causa: str) -> None:
    rodadas = ((store.get("ingestao_causas") or {}).get("rodadas", []) + [causa])[-RODADAS:]
    dominante = max(reversed(rodadas), key=rodadas.count)          # empate: a mais recente
    store.set("ingestao_causas", {"rodadas": rodadas, "dominante": dominante})


def girar(pasta: str | Path, store: Store, agora: float | None = None) -> int:
    """Passa a pasta, grava a causa da rodada, conta os giros seguidos com a mesma causa e abre ou fecha o pedido;
    devolve os lançamentos novos."""
    pasta = Path(pasta)
    pendentes = len(_extratos(pasta))
    novos = 0
    try:
        novos = ingerir_pasta(pasta, store)
    finally:
        _registrar(store, causa_da_rodada(store.get("lancamentos_motivo"), pendentes, novos))
    causa = store.get("lancamentos_motivo")
    causa = causa if causa in CAUSAS else None
    agora = time.time() if agora is None else agora
    _esquema(store)
    store.x("UPDATE pedidos_ingestao SET fechado_em=? WHERE fechado_em IS NULL AND causa IS NOT ?", (agora, causa))
    seguidos = store.get("ingestao_giros") or {}
    n = seguidos.get(causa, 0) + 1 if causa else 0
    store.set("ingestao_giros", {causa: n} if causa else {})
    if causa and n >= GIROS:
        store.x("INSERT OR IGNORE INTO pedidos_ingestao(causa, pasta, mensagem, aberto_em) VALUES(?,?,?,?)",
                (causa, str(pasta), mensagem(causa, pasta), agora))
    return novos


def abertos(store: Store) -> list[dict]:
    _esquema(store)
    return [dict(r) for r in store.q("SELECT * FROM pedidos_ingestao WHERE fechado_em IS NULL ORDER BY id")]
