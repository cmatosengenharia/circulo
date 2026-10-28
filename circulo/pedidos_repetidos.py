"""Pergunta #399 (entrevistador_jtbd): pedido do humano que reformula um anterior é sinal de que a entrega não resolveu.

Repetição = mesmo alvo (o módulo do item, senão o primeiro arquivo citado no texto) e Jaccard ≥ MIN_JACCARD entre os
tokens normalizados (minúsculas, sem acento, sem stopwords) em até 7 dias. Cada repetição forma o par com o pedido
parecido mais recente antes dela: esse original é o que fica marcado como 'entrega_nao_resolveu'. `pares` é pura, sem DB nem LLM.
"""
from __future__ import annotations

import re
import time

from .memoria import termos

JANELA = 7 * 86400
MIN_JACCARD = 0.6
_ARQUIVO = re.compile(r"[\w./-]+\.(?:py|html|md|json|toml|ya?ml)\b")


def alvo(pedido) -> str:
    """O arquivo alvo do pedido; '' quando nem o módulo nem o texto apontam um."""
    if pedido.get("modulo"):
        return pedido["modulo"]
    m = _ARQUIVO.search(f"{pedido['titulo']} {pedido.get('detalhe') or ''}")
    return m.group(0) if m else ""


def _tokens(pedido) -> set[str]:
    return set(termos(f"{pedido['titulo']} {pedido.get('detalhe') or ''}", 10**6))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def pares(pedidos) -> list[tuple]:
    """(original, repetição) na ordem em que as repetições chegaram."""
    ordem = sorted(pedidos, key=lambda p: p["created_at"])
    feitos = [(p, alvo(p), _tokens(p)) for p in ordem]
    out = []
    for i, (q, aq, tq) in enumerate(feitos):
        for p, ap, tp in reversed(feitos[:i]):
            if ap == aq and q["created_at"] - p["created_at"] <= JANELA and _jaccard(tp, tq) >= MIN_JACCARD:
                out.append((p, q))
                break
    return out


def repeticoes_7d(store, agora: float | None = None) -> int:
    """Quantos pedidos 'pedido_cassio' dos últimos 7 dias repetem um anterior da mesma janela."""
    agora = time.time() if agora is None else agora
    return len(pares([dict(r) for r in store.q("SELECT titulo, detalhe, modulo, created_at FROM roadmap "
                                               "WHERE origem='pedido_cassio' AND created_at>=?", (agora - JANELA,))]))
