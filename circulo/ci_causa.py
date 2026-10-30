"""Causa da falha de CI pelos sinais diretos da API de checks, não pela contagem de checks que caíram.

Os 7 checks caindo juntos não separam infra de código: um erro de import derruba todos (PRs #80 a #84, main vermelha),
e o limite de gasto também (#86). A causa parte de cada check: startup_failure, job que não iniciou ou anotação de
cobrança/runner são infra; falha total sem esses sinais é só um sinal fraco, que pede o reexecute local (main vs
branch) antes de reabrir; falha parcial é código.
"""
from __future__ import annotations

import re

INFRA, CODIGO_OU_INDETERMINADO, CODIGO = "infra_suspeita", "codigo_ou_indeterminado", "codigo"
PASSOU = ("success", "skipped", "neutral", None)
NAO_INICIADO = ("queued", "waiting", "pending", "requested")
ASSINATURA_INFRA = re.compile(r"was not started|spending limit|payments have failed|billing|\brunner\b", re.I)


def _infra(c: dict) -> bool:
    return (c.get("conclusion") == "startup_failure" or c.get("status") in NAO_INICIADO or bool(c.get("sem_passos"))
            or bool(ASSINATURA_INFRA.search(c.get("anotacao") or "")))


def classificar(checks: list[dict]) -> str | None:
    """Cada check com conclusion, status e anotação → infra_suspeita (todo check falho com sinal de infra),
    codigo_ou_indeterminado (todos falharam e algum sem sinal de infra), codigo (falha parcial); None se nada falhou."""
    falhos = [c for c in checks if c.get("conclusion") not in PASSOU]
    if not falhos:
        return None
    if all(_infra(c) for c in falhos):
        return INFRA
    return CODIGO_OU_INDETERMINADO if len(falhos) == len(checks) else CODIGO


def apos_reexecucao(main_ok: bool, branch_ok: bool) -> str:
    """O reexecute local desempata codigo_ou_indeterminado: a branch falha = código; main e branch passam = o CI
    falhou fora do código (infra); só a main falha = segue indeterminado."""
    if not branch_ok:
        return CODIGO
    return INFRA if main_ok else CODIGO_OU_INDETERMINADO


# Ordem de causa-raiz (lição #53): o primeiro vermelho dela é a raiz e os demais são derivados. Cada check com o
# comando que o reproduz localmente; Testes 3.12/3.13 dividem o mesmo posto (o 3.12 vem antes no desempate).
CONSTITUICAO = ("circulo/merge_gate.py circulo/policy.py circulo/budget.py circulo/guardrails.py circulo/self_dev.py "
                "circulo/corpo.py .github/")
ORDEM_RAIZ = (
    ("Constituição", f"git diff --name-only origin/main HEAD -- {CONSTITUICAO}"),
    ("Reprodução primeiro", "python -m circulo.reproducao --base origin/main --head HEAD"),
    ("Testes (Python 3.11)", "python3.11 -m pytest -q"),
    ("Testes (Python 3.12)", "python3.12 -m pytest -q"),
    ("Testes (Python 3.13)", "python3.13 -m pytest -q"),
    ("Container", "docker build -q -t circulo:ci ."),
    ("Evidência reforçada", "python -m pytest -q tests/test_propriedades_financeiras.py"),
)
MIN_JUNTOS = 3
PELA_REGRA = "pela_regra"


def raiz(falhando: list[str]) -> dict | None:
    """Nomes dos checks vermelhos → {check, acao: rodar_local, comando, derivados, decisao: pela_regra}: com ≥3 juntos,
    só o primeiro da ORDEM_RAIZ vira ação e os outros são consequência. None com menos de 3 ou com check fora da ordem
    (fica para o Jev)."""
    nomes = dict(ORDEM_RAIZ)
    if len(set(falhando)) < MIN_JUNTOS or any(n not in nomes for n in falhando):
        return None
    check = next(n for n, _ in ORDEM_RAIZ if n in falhando)
    return {"check": check, "acao": "rodar_local", "comando": nomes[check],
            "derivados": [n for n, _ in ORDEM_RAIZ if n in falhando and n != check], "decisao": PELA_REGRA}


def do_run(r: dict) -> dict:
    """Check do GitHubREST (merge_gate) → o que `classificar` lê, com a anotação de não iniciado e o job sem passos."""
    return {"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion"),
            "anotacao": r.get("nao_iniciado") or r.get("anotacao") or "", "sem_passos": bool(r.get("sem_passos"))}
