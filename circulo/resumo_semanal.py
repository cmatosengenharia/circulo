"""Resumo semanal para a equipe: o changelog (produto/infra, cada PR com o pedido de origem, e a fração de produto
contra a meta), os PRs sem pedido listados à parte, o uso medido (leituras do digest em 7 dias) e as consultas 7d de cada PR de produto,
com os que ninguém consultou sinalizados. Cada consulta fica em `uso_resumo` (recurso, created_at): 'resumo' e
'pr:<número>' de cada PR de produto mostrado. Compõe `changelog` e `digest_semanal`; não refaz a coleta nem a
classificação."""
from __future__ import annotations

import time

from . import changelog, digest_semanal, norte
from .state import Store

ESQUEMA = """
CREATE TABLE IF NOT EXISTS uso_resumo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recurso TEXT NOT NULL,
  created_at REAL NOT NULL
)
"""


def texto(prs: list[dict], leituras: int, consultas: dict[int, int] | None = None) -> str:
    """O resumo em markdown a partir dos PRs mergeados na semana (number, titulo, produto, pedido) e das consultas 7d
    por número de PR. Pura."""
    consultas = consultas or {}
    sem_pedido = sorted((p for p in prs if not p["pedido"]), key=lambda p: p["number"])
    produto = sorted((p for p in prs if p["produto"]), key=lambda p: p["number"])
    sem_uso = [p for p in produto if not consultas.get(p["number"])]
    linhas = [changelog.texto(prs), "", f"## Sem pedido ({len(sem_pedido)})"]
    linhas += [f"- #{p['number']} {p['titulo']} ({'produto' if p['produto'] else 'infra'})" for p in sem_pedido]
    linhas += ["", f"## Consultas 7d ({len(produto)} PRs de produto)"]
    linhas += [f"- #{p['number']} {p['titulo']} · consultas 7d: {consultas.get(p['number'], 0)}" for p in produto]
    linhas += ["", f"## Produto sem uso ({len(sem_uso)})"]
    linhas += [f"- #{p['number']} {p['titulo']}" for p in sem_uso]
    linhas += ["", f"Lido {leituras} vezes nos últimos 7 dias."]
    return "\n".join(linhas)


def consultas(store: Store, agora: float | None = None) -> dict[int, int]:
    """Consultas de cada PR (por número) em `uso_resumo` nos últimos 7 dias."""
    agora = time.time() if agora is None else agora
    store.x(ESQUEMA)
    return {int(r["recurso"][3:]): r["n"] for r in store.q(
        "SELECT recurso, COUNT(*) n FROM uso_resumo WHERE recurso LIKE 'pr:%' AND created_at>=? GROUP BY recurso",
        (agora - norte.SEMANA,))}


def semana(store: Store, agora: float | None = None) -> str:
    """O resumo dos últimos 7 dias. As consultas 7d são medidas antes desta, que então é registrada em `uso_resumo`
    (o resumo e cada PR de produto mostrado) e conta no uso medido do digest."""
    agora = time.time() if agora is None else agora
    digest_semanal.ler(store, agora)
    prs = digest_semanal.prs_da_semana(store, agora)
    t = texto(prs, digest_semanal.leituras(store, agora), consultas(store, agora))
    for recurso in ["resumo"] + [f"pr:{p['number']}" for p in prs if p["produto"]]:
        store.x("INSERT INTO uso_resumo(recurso, created_at) VALUES(?,?)", (recurso, agora))
    return t
