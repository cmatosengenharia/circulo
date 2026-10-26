"""Resumo semanal para a equipe: o changelog (produto/infra, cada PR com o pedido de origem, e a fração de produto
contra a meta), os PRs sem pedido listados à parte e o uso medido (leituras do digest em 7 dias). Compõe `changelog`
e `digest_semanal`; não refaz a coleta nem a classificação."""
from __future__ import annotations

from . import changelog, digest_semanal
from .state import Store


def texto(prs: list[dict], leituras: int) -> str:
    """O resumo em markdown a partir dos PRs mergeados na semana (number, titulo, produto, pedido). Pura."""
    sem_pedido = sorted((p for p in prs if not p["pedido"]), key=lambda p: p["number"])
    linhas = [changelog.texto(prs), "", f"## Sem pedido ({len(sem_pedido)})"]
    linhas += [f"- #{p['number']} {p['titulo']} ({'produto' if p['produto'] else 'infra'})" for p in sem_pedido]
    linhas += ["", f"Lido {leituras} vezes nos últimos 7 dias."]
    return "\n".join(linhas)


def semana(store: Store, agora: float | None = None) -> str:
    """O resumo dos últimos 7 dias; a leitura conta no uso medido do digest."""
    digest_semanal.ler(store, agora)
    return texto(digest_semanal.prs_da_semana(store, agora), digest_semanal.leituras(store, agora))
