"""Prova de melhora por item mergeado (pergunta do conselho #57): a métrica do critério de sucesso do item, lida no
planejamento (antes) e 7 dias depois do merge (depois), gravada na trilha (`elos`: item:N → medicao:N:antes|depois).

Item sem critério não tem prova: o lead time de PR mediano (minutos, da abertura ao merge, nos 7 dias anteriores) só
entra como proxy marcado e contado à parte. É métrica de entrega (DORA), não diz se o objetivo do item foi atingido.

`medir` é pura; `registrar` lê o banco, chama `medir` e grava os elos (idempotente).
"""
from __future__ import annotations

import re
import statistics
from typing import Callable

from .rastro import PREFIXO_BRANCH, elo
from .state import Store

JANELA_S = 7 * 86400
PROXY = "lead_time_pr_mediano_min"
_SUCESSO = re.compile(r"^Sucesso:[ \t]*(.*?)\s*$", re.M)

Leitor = Callable[[str, float], "float | None"]   # (métrica do critério, instante) → valor; None: sem leitura


def criterio(detalhe: str) -> str | None:
    """O critério de sucesso do item: a linha `Sucesso:` que o planejador grava no detalhe."""
    m = _SUCESSO.search(detalhe or "")
    return m.group(1) if m and m.group(1) else None


def lead_time_mediano_min(prs: list[tuple[float, float]], ate: float) -> float | None:
    """Mediana, em minutos, de (aberto → mergeado) dos PRs mergeados nos 7 dias antes de `ate`."""
    lt = [(m - a) / 60 for a, m in prs if ate - JANELA_S <= m < ate]
    return statistics.median(lt) if lt else None


def medir(itens: list[dict], prs: list[tuple[float, float]], agora: float, ler: Leitor) -> dict:
    """Antes (no planejamento) e depois (7 d pós-merge) de cada item mergeado, e as contagens do relatório."""
    medicoes, n = [], {"com_antes_depois": 0, "sem_criterio": 0, "sem_medicao": 0, "proxy_com_antes_depois": 0}
    for it in itens:
        apos = it["mergeado_em"] + JANELA_S
        metrica = criterio(it["detalhe"])
        if metrica:
            antes, depois = ler(metrica, it["criado_em"]), ler(metrica, apos) if agora >= apos else None
        else:
            antes = lead_time_mediano_min(prs, it["criado_em"])
            depois = lead_time_mediano_min(prs, apos) if agora >= apos else None
        completo = antes is not None and depois is not None
        if not metrica:
            n["sem_criterio"] += 1
            n["proxy_com_antes_depois"] += completo
        else:
            n["com_antes_depois" if completo else "sem_medicao"] += 1
        medicoes.append({"item": it["id"], "metrica": metrica or PROXY, "proxy": not metrica, "antes": antes, "depois": depois})
    return {**n, "medicoes": medicoes}


def registrar(store: Store, agora: float, ler: Leitor) -> dict:
    """Mede todo item com PR mergeado e grava antes/depois na trilha; devolve o relatório de `medir`."""
    itens = [dict(r) for r in store.q(
        "SELECT r.id, r.detalhe, r.created_at criado_em, MIN(m.created_at) mergeado_em FROM roadmap r "
        "JOIN prs p ON p.branch LIKE ? || r.id || '-%' JOIN merges m ON m.pr=p.number AND m.merged=1 "
        "GROUP BY r.id ORDER BY r.id", (PREFIXO_BRANCH,))]
    prs = [(r["a"], r["m"]) for r in store.q(
        "SELECT p.created_at a, MIN(m.created_at) m FROM prs p JOIN merges m ON m.pr=p.number AND m.merged=1 GROUP BY p.number")]
    r = medir(itens, prs, agora, ler)
    for it, med in zip(itens, r["medicoes"], strict=True):
        for fase, em in (("antes", it["criado_em"]), ("depois", it["mergeado_em"] + JANELA_S)):
            if med[fase] is not None:
                elo(store, f"item:{med['item']}", f"medicao:{med['item']}:{fase}", "mediu",
                    {"metrica": med["metrica"], "proxy": med["proxy"], "valor": med[fase], "em": em})
    return r
