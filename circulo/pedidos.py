"""Canal de origem de cada pedido (pergunta do conselho #441): só mede, não integra Slack nem GitHub.

`Store.enqueue` grava `canal` no payload de todo pedido; `por_canal_7d` alimenta a evidência geral do Planejador,
para decidir com número se vale abrir pedido direto de issue, comentário de PR ou Slack."""
from __future__ import annotations

import time

from .jobs import HUMANO, JANELA

CANAIS = ("painel", "issue", "comentario_pr", "slack")
DESCONHECIDO = "desconhecido"


def canal(payload: dict) -> str:
    """O canal declarado (ou a origem) se for um dos conhecidos; qualquer outro vira 'desconhecido'."""
    c = payload.get("canal") or payload.get("origem")
    return c if c in CANAIS else DESCONHECIDO


def por_canal_7d(store, agora: float | None = None) -> dict[str, int]:
    """Pedidos humanos dos últimos 7 dias por canal; todo canal aparece, mesmo com zero."""
    agora = time.time() if agora is None else agora
    rows = store.q(f"SELECT COALESCE(json_extract(payload,'$.canal'),'{DESCONHECIDO}') canal, COUNT(*) n FROM events "
                   f"WHERE {HUMANO} AND created_at>? GROUP BY 1", (agora - JANELA,))
    contagem = dict.fromkeys((*CANAIS, DESCONHECIDO), 0)
    for r in rows:
        contagem[r["canal"] if r["canal"] in contagem else DESCONHECIDO] += r["n"]
    return contagem
