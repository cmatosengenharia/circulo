"""Changelog semanal: os PRs mergeados em 7 dias agrupados em produto e infra, cada um com o pedido de origem, e a
fração de produto contra a meta do Norte. Usa os PRs de `digest_semanal.prs_da_semana`; PR sem origem sai marcado
'sem pedido', nunca omitido."""
from __future__ import annotations

from . import digest_semanal
from .state import Store


def texto(prs: list[dict]) -> str:
    """O changelog em markdown a partir dos PRs mergeados na semana (number, titulo, produto, pedido). Pura."""
    produto = sorted((p for p in prs if p["produto"]), key=lambda p: p["number"])
    infra = sorted((p for p in prs if not p["produto"]), key=lambda p: p["number"])
    fracao = f"{len(produto) / len(prs):.2f}" if prs else "—"
    linhas = ["# Changelog semanal", "",
              f"{len(produto)} de {len(prs)} PRs foram produto (fração {fracao}, meta {digest_semanal.META})."]
    for nome, grupo in (("Produto", produto), ("Infra", infra)):
        linhas += ["", f"## {nome} ({len(grupo)})"]
        linhas += [f"- #{p['number']} {p['titulo']} · {p['pedido'] or digest_semanal.SEM_PEDIDO}" for p in grupo]
    return "\n".join(linhas)


def semana(store: Store, agora: float | None = None) -> str:
    """O changelog dos PRs mergeados nos últimos 7 dias."""
    return texto(digest_semanal.prs_da_semana(store, agora))
