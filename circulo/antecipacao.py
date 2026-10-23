"""Cobertura de antecipação: que fração dos pedidos humanos de 7 dias já tinha um item proativo ('antecipar:<job>')
criado antes dele, e quais jobs recorrentes ainda não tiveram nenhum pedido antecipado."""
from __future__ import annotations

import time
from typing import NamedTuple

from .jobs import MIN_OCORRENCIAS, pedidos_7d, recorrentes

META = 0.25      # fração dos pedidos da semana que o loop deveria ter entregue antes de ser pedido
PREFIXO = "antecipar:"


class Cobertura(NamedTuple):
    total: int                   # pedidos considerados
    antecipados: int             # deles, os que já tinham item proativo do mesmo job criado antes
    cobertura: float             # antecipados / total
    sem_antecipacao: list[str]   # jobs recorrentes sem nenhum pedido antecipado, do mais pedido ao menos


def cobertura(pedidos, itens, minimo: int = MIN_OCORRENCIAS) -> Cobertura:
    """Cruza o job de cada pedido com os itens 'antecipar:<job>' criados antes dele; pura, sem DB nem LLM."""
    primeiro: dict[str, float] = {}
    for i in itens:
        if i["nome"].startswith(PREFIXO):
            job = i["nome"][len(PREFIXO):]
            primeiro[job] = min(primeiro.get(job, i["created_at"]), i["created_at"])
    antecipados = [p for p in pedidos if p["job"] in primeiro and primeiro[p["job"]] < p["created_at"]]
    cobertos = {p["job"] for p in antecipados}
    total = len(pedidos)
    return Cobertura(total, len(antecipados), round(len(antecipados) / total, 3) if total else 0.0,
                     [j for j in recorrentes(pedidos, minimo).jobs if j not in cobertos])


def medir(store, agora: float | None = None) -> Cobertura:
    agora = time.time() if agora is None else agora
    itens = store.q("SELECT nome, created_at FROM projects WHERE nome LIKE ? AND created_at<=?", (PREFIXO + "%", agora))
    return cobertura(pedidos_7d(store, agora), itens)
