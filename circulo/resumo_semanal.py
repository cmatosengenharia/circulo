"""Resumo semanal para a equipe: o changelog (produto/infra, cada PR com o pedido de origem, e a fração de produto
contra a meta), os PRs sem pedido listados à parte, o uso medido (leituras do digest em 7 dias) e as consultas 7d de cada PR de produto,
com os que ninguém consultou sinalizados, e os pedidos abertos ainda sem PR de produto mergeado, do mais velho ao mais
novo, para a equipe ver o que vem a seguir. Cada consulta fica em `uso_resumo` (recurso, created_at): 'resumo' e
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


def pedidos_sem_entrega(pedidos: list[dict], prs: list[dict], agora: float) -> list[dict]:
    """Os pedidos (id, titulo, created_at) sem nenhum PR mergeado (item_id) apontando para eles, com a idade em dias,
    do mais velho ao mais novo. Pura."""
    entregues = {p["item_id"] for p in prs}
    abertos = sorted((p for p in pedidos if p["id"] not in entregues), key=lambda p: (p["created_at"], p["id"]))
    return [{"id": p["id"], "titulo": p["titulo"], "dias": int((agora - p["created_at"]) // 86400)} for p in abertos]


def texto(prs: list[dict], leituras: int, consultas: dict[int, int] | None = None,
          sem_entrega: list[dict] | None = None) -> str:
    """O resumo em markdown a partir dos PRs mergeados na semana (number, titulo, produto, pedido), das consultas 7d
    por número de PR e dos pedidos sem entrega (`pedidos_sem_entrega`). Pura."""
    consultas, sem_entrega = consultas or {}, sem_entrega or []
    sem_pedido = sorted((p for p in prs if not p["pedido"]), key=lambda p: p["number"])
    produto = sorted((p for p in prs if p["produto"]), key=lambda p: p["number"])
    sem_uso = [p for p in produto if not consultas.get(p["number"])]
    linhas = [changelog.texto(prs), "", f"## Sem pedido ({len(sem_pedido)})"]
    linhas += [f"- #{p['number']} {p['titulo']} ({'produto' if p['produto'] else 'infra'})" for p in sem_pedido]
    linhas += ["", f"## Consultas 7d ({len(produto)} PRs de produto)"]
    linhas += [f"- #{p['number']} {p['titulo']} · consultas 7d: {consultas.get(p['number'], 0)}" for p in produto]
    linhas += ["", f"## Produto sem uso ({len(sem_uso)})"]
    linhas += [f"- #{p['number']} {p['titulo']}" for p in sem_uso]
    linhas += ["", f"## Pedidos sem entrega ({len(sem_entrega)})"]
    linhas += [f"- item #{p['id']} {p['titulo']} · {p['dias']} dia{'' if p['dias'] == 1 else 's'}" for p in sem_entrega]
    linhas += ["", f"Lido {leituras} vezes nos últimos 7 dias."]
    return "\n".join(linhas)


def consultas(store: Store, agora: float | None = None) -> dict[int, int]:
    """Consultas de cada PR (por número) em `uso_resumo` nos últimos 7 dias."""
    agora = time.time() if agora is None else agora
    store.x(ESQUEMA)
    return {int(r["recurso"][3:]): r["n"] for r in store.q(
        "SELECT recurso, COUNT(*) n FROM uso_resumo WHERE recurso LIKE 'pr:%' AND created_at>=? GROUP BY recurso",
        (agora - norte.SEMANA,))}


def sem_entrega(store: Store, agora: float) -> list[dict]:
    """Os pedidos abertos do roteiro (pedido_cassio, ativos, não feitos) sem PR mergeado, de qualquer idade."""
    pedidos = [dict(r) for r in store.q("SELECT id, titulo, created_at FROM roadmap WHERE origem='pedido_cassio' "
                                        "AND status!='feito' AND COALESCE(desativado,0)=0")]
    prs = [dict(r) for r in store.q("SELECT item_id FROM prs WHERE status='mergeado' AND item_id IS NOT NULL")]
    return pedidos_sem_entrega(pedidos, prs, agora)


def semana(store: Store, agora: float | None = None) -> str:
    """O resumo dos últimos 7 dias. As consultas 7d são medidas antes desta, que então é registrada em `uso_resumo`
    (o resumo e cada PR de produto mostrado) e conta no uso medido do digest."""
    agora = time.time() if agora is None else agora
    digest_semanal.ler(store, agora)
    prs = digest_semanal.prs_da_semana(store, agora)
    t = texto(prs, digest_semanal.leituras(store, agora), consultas(store, agora), sem_entrega(store, agora))
    for recurso in ["resumo"] + [f"pr:{p['number']}" for p in prs if p["produto"]]:
        store.x("INSERT INTO uso_resumo(recurso, created_at) VALUES(?,?)", (recurso, agora))
    return t
