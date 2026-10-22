"""Portão de reincidência (pergunta do conselho #85): não abrir PR de item que já fechou 2x sem merge com os mesmos checks.

Os PRs #82, #83 e #84 (mesmo título) fecharam sem merge com os mesmos 7 checks falhando; o developer gastou 2,88M tokens
em 7 dias. Como no circuit breaker (Fowler), após LIMIAR fechamentos seguidos do mesmo título com o mesmo conjunto de
checks, o item é vetado antes de qualquer chamada do Developer e volta para diagnóstico. Desarma quando o último
fechamento traz outro conjunto ou o item é reescrito (outro título). Complementa `pre_pr` (main vermelha, falha
uniforme): lá a chave é o CI, aqui é o item. Mede-se pela verificação `developer:abrir_pr:vetar` contra os PRs abertos
para títulos já vetados.
"""
from __future__ import annotations

from collections.abc import Iterable

from .gate_causa import checks_falhando
from .pre_pr import ABRIR, Decisao

VETAR, REINCIDENCIA = "vetado", "reincidencia"
VETO_PONTO = "developer:abrir_pr:vetar"
LIMIAR = 2


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
    """Os PRs fechados sem merge por checks (o último motivo do gate é o que fechou), do mais recente."""
    out = []
    for r in store.q("SELECT p.titulo, m.reason FROM prs p JOIN merges m ON m.pr=p.number WHERE p.status='fechado' "
                     "AND m.id=(SELECT MAX(id) FROM merges WHERE pr=p.number AND merged=0) "
                     "ORDER BY p.updated_at DESC, p.number DESC"):
        falhos = checks_falhando(r["reason"])
        if falhos is not None:
            out.append((r["titulo"], falhos))
    return out
