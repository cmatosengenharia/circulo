"""Orçamento diário de tokens vindo da configuração, com aviso antes do corte.

O padrão do dia é CIRCULO_TOKENS_DIA (1 milhão sem a variável), dentro do teto duro da constituição; o limite que
você escolhe no painel continua valendo por cima. A cada giro o loop avisa uma vez quando o gasto do dia cruza 50%
e 80%; em 100% o giro pausa (Budget.exhausted) e só você sobe o limite, pelo painel.
"""
from __future__ import annotations

import os
from typing import Callable

from .budget import LIMITE_MIN, Budget, limite_diario
from .policy import HARD_DAILY_TOKEN_CAP
from .state import Store

TOKENS_DIA = 1_000_000
MARCOS = (50, 80, 100)


def tokens_dia() -> int:
    try:
        n = int(os.environ.get("CIRCULO_TOKENS_DIA", TOKENS_DIA))
    except ValueError:
        n = TOKENS_DIA
    return max(LIMITE_MIN, min(n, HARD_DAILY_TOKEN_CAP))


def com_tokens_dia(policy: dict) -> dict:
    """A política que o porteiro do gasto enxerga: o limite diário é o da configuração, não o da semente."""
    return {**policy, "budget": {**policy["budget"], "daily_token_limit": tokens_dia()}}


def limite_hoje(store: Store) -> int:
    return limite_diario(store, tokens_dia())


def tokens_por_job(store: Store, desde: float = 0.0) -> dict[str, int]:
    return {r["job"]: int(r["t"]) for r in store.q(
        "SELECT COALESCE(job,'desconhecido') job, SUM(tokens) t FROM llm_calls WHERE created_at>=? GROUP BY 1 ORDER BY t DESC",
        (desde,))}


def avisar_marcos(store: Store, budget: Budget, reply: Callable[[str, str], None]) -> int | None:
    """Avisa uma vez por marco cruzado no dia (e de novo se você mudar o limite). Devolve o marco avisado."""
    b = budget.snapshot()
    usado, limite = int(b["tokens"]), int(b["limite"])
    pct = 100 * usado // limite if limite else 100
    marco = max((m for m in MARCOS if pct >= m), default=None)
    visto = store.get("orcamento_marco") or {}
    if marco is None or (visto.get("dia"), visto.get("limite")) == (b["dia"], limite) and visto.get("marco", 0) >= marco:
        return None
    store.set("orcamento_marco", {"dia": b["dia"], "limite": limite, "marco": marco})
    conta = f"{usado:,} de {limite:,} tokens".replace(",", ".")
    if marco < 100:
        reply(f"Orçamento do dia em {marco}% ({conta}). Em 100% o loop pausa as chamadas de LLM até a meia-noite.", "orcamento")
    else:
        reply(f"Orçamento do dia em 100% ({conta}): o loop pausou as chamadas de LLM até a meia-noite. "
              "Para seguir hoje, suba o limite no painel.", "orcamento")
    return marco
