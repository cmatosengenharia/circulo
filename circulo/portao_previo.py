"""Portão de reincidência (pergunta do conselho #85): não abrir PR de item que já fechou 2x sem merge com os mesmos checks.

Os PRs #80 a #84 (mesmo título) fecharam sem merge com os mesmos 7 checks falhando; o developer gastou 2,88M tokens
em 7 dias. Como na fila de descarte (DLQ) depois do máximo de tentativas, após LIMIAR fechamentos seguidos do mesmo
título com o mesmo conjunto de checks a falha é durável: o item vai para 'descartado' com a causa, antes de qualquer
chamada do Developer. Desarma quando o último fechamento traz outro conjunto ou o item é reescrito (outro título).
`circulo redrive --item N` reabre (redrive): os fechamentos até ali deixam de contar. Complementa `pre_pr` (main
vermelha, falha uniforme): lá a chave é o CI, aqui é o item. Mede-se pela verificação `developer:abrir_pr:vetar`
contra os PRs abertos para títulos já vetados.
"""
from __future__ import annotations

import time
from collections.abc import Iterable

from .gate_causa import checks_falhando
from .pre_pr import ABRIR, Decisao

VETAR, REINCIDENCIA = "vetado", "reincidencia"
VETO_PONTO = "developer:abrir_pr:vetar"
LIMIAR = 2
DESCARTADO = "descartado"
REDRIVE = "portao_previo_redrive"          # {título normalizado: maior PR fechado que já não conta}


def normalizar(titulo: str) -> str:
    return " ".join((titulo or "").split()).casefold()


def decidir(titulo: str, fechados: Iterable[tuple[str, Iterable[str]]], limiar: int = LIMIAR) -> Decisao:
    """(título, checks falhando) de cada PR fechado sem merge, do mais recente → abrir ou vetar o item."""
    alvo = normalizar(titulo)
    ultimos = [frozenset(c) for t, c in fechados if normalizar(t) == alvo][:limiar]
    if len(ultimos) == limiar and ultimos[0] and all(c == ultimos[0] for c in ultimos):
        return Decisao(VETAR, REINCIDENCIA)
    return Decisao(ABRIR)


def fechados_sem_merge(store) -> list[tuple[str, set[str]]]:
    """Os PRs fechados sem merge por checks (o último motivo do gate é o que fechou), do mais recente; os anteriores
    ao redrive do título não contam."""
    marcas, out = store.get(REDRIVE) or {}, []
    for r in store.q("SELECT p.number, p.titulo, m.reason FROM prs p JOIN merges m ON m.pr=p.number WHERE p.status='fechado' "
                     "AND m.id=(SELECT MAX(id) FROM merges WHERE pr=p.number AND merged=0) "
                     "ORDER BY p.updated_at DESC, p.number DESC"):
        falhos = checks_falhando(r["reason"])
        if falhos is not None and r["number"] > marcas.get(normalizar(r["titulo"]), 0):
            out.append((r["titulo"], falhos))
    return out


def redrive(store, item_id: int) -> str:
    """Reabertura manual do item descartado: volta para a fila e os PRs fechados até aqui deixam de contar."""
    item = store.one("SELECT titulo FROM roadmap WHERE id=? AND status=?", (item_id, DESCARTADO))
    if item is None:
        return f"item #{item_id} não está descartado: nada a reabrir"
    alvo = normalizar(item["titulo"])
    ultimo = max((r["number"] for r in store.q("SELECT number, titulo FROM prs WHERE status='fechado'")
                  if normalizar(r["titulo"]) == alvo), default=0)
    store.set(REDRIVE, {**(store.get(REDRIVE) or {}), alvo: ultimo})
    texto = f"redrive: reaberto por você; os PRs fechados até o #{ultimo} não contam mais"
    store.x("UPDATE roadmap SET status='pendente', evidencia=?, updated_at=? WHERE id=?", (texto, time.time(), item_id))
    return f"item #{item_id} {texto}"
