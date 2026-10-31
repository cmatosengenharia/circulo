"""Latência até o merge (pergunta do conselho #695): só lê as decisões do gate (tabela `merges`).

O tempo entre duas decisões consecutivas do mesmo PR conta para a etapa da primeira, pelo motivo dela: 'checks em
andamento'/'checks ausentes' = CI, 'atrás da main' = rebase, 'todos os gates passaram' = merge; o resto é 'outra'.
`mais_lentos` devolve os 5 PRs mergeados nos últimos 7 dias que mais demoraram da primeira decisão ao merge, cada um
com a etapa dominante e o percentual dela; `texto` é o que o console (`circulo latencia`) mostra."""
from __future__ import annotations

import time

from .caminho import CI_EM_CURSO, _dur

JANELA = 7 * 86400
QUANTOS = 5
NOMES = {"ci": "CI", "rebase": "rebase", "merge": "merge", "outra": "outra"}


def etapa(motivo: str) -> str:
    motivo = motivo or ""
    if motivo.startswith(CI_EM_CURSO):
        return "ci"
    if "atrás da main" in motivo:
        return "rebase"
    return "merge" if motivo.startswith("todos os gates passaram") else "outra"


def _por_etapa(decisoes) -> dict[str, float]:
    soma: dict[str, float] = {}
    for a, b in zip(decisoes, decisoes[1:], strict=False):
        e = etapa(a["reason"])
        soma[e] = soma.get(e, 0.0) + b["created_at"] - a["created_at"]
    return soma


def mais_lentos(store, agora: float | None = None, n: int = QUANTOS) -> list[dict]:
    agora = time.time() if agora is None else agora
    prs = []
    for m in store.q("SELECT pr, MIN(id) id, MIN(created_at) em FROM merges WHERE merged=1 GROUP BY pr HAVING em>=?",
                     (agora - JANELA,)):
        decisoes = store.q("SELECT reason, created_at FROM merges WHERE pr=? AND id<=? ORDER BY id", (m["pr"], m["id"]))
        total = m["em"] - decisoes[0]["created_at"]
        soma = _por_etapa(decisoes)
        dominante = max(soma, key=soma.get) if soma else "merge"
        prs.append({"pr": m["pr"], "decisoes": len(decisoes), "total_s": total, "por_etapa": soma, "etapa": dominante,
                    "pct": round(100 * soma[dominante] / total) if total > 0 else 100})
    return sorted(prs, key=lambda p: -p["total_s"])[:n]


def texto(lentos: list[dict]) -> str:
    if not lentos:
        return "Nenhum PR mergeado nos últimos 7 dias."
    linhas = [f"Os {len(lentos)} PRs mais lentos dos últimos 7 dias (primeira decisão do gate → merge):"]
    for p in lentos:
        linhas.append(f"  PR #{p['pr']}: {_dur(p['total_s'])}, {p['decisoes']} decisões — {NOMES[p['etapa']]} {p['pct']}%")
    return "\n".join(linhas)
