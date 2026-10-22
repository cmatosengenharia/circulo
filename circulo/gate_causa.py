"""Causa da falha de checks no gate (pergunta do conselho #76): o PR caiu sozinho ou com o CI inteiro?

Os PRs #48, #49, #50 e #80 a #84 fecharam com os mesmos 7 checks falhando juntos, inclusive Constituição e Container,
que nenhum PR de código derruba (lição #53): a falha 'uniforme' é do CI, não do PR. `baseline` mede a fração de PRs
fechados assim e os tokens do developer gastos neles; é o número que o portão pré-PR (item #125, `pre_pr.py`) precisa
derrubar a 0 para provar economia.
"""
from __future__ import annotations

from .merge_gate import REQUIRED_CHECKS
from .reparo import tokens_do_item

FALHANDO = "checks falhando: "
TODOS_OS_CHECKS = frozenset((*REQUIRED_CHECKS, "Container", "Reprodução primeiro"))
UNIFORME, ESPECIFICA = "uniforme", "especifica"


def checks_falhando(motivo: str) -> set[str] | None:
    """Os checks citados na 1ª linha do motivo 'checks falhando: ...' do gate; None se o motivo é outro."""
    primeira = (motivo or "").split("\n", 1)[0]
    if not primeira.startswith(FALHANDO):
        return None
    return {c.strip() for c in primeira[len(FALHANDO):].split(",") if c.strip()}


def classificar(motivo: str) -> str | None:
    """'uniforme' quando os 7 checks falham juntos, 'especifica' quando só parte deles; None se não é falha de checks."""
    falhos = checks_falhando(motivo)
    if falhos is None:
        return None
    return UNIFORME if TODOS_OS_CHECKS <= falhos else ESPECIFICA


def baseline(store) -> dict:
    """Entre os PRs fechados sem merge por checks (o último motivo do gate é o que fechou), a fração uniforme e os
    tokens do developer nesses PRs (rodada principal, reparo e conserto)."""
    fechados = store.q("SELECT p.number, p.titulo, m.reason FROM prs p JOIN merges m ON m.pr=p.number "
                       "WHERE p.status='fechado' AND m.id=(SELECT MAX(id) FROM merges WHERE pr=p.number AND merged=0)")
    causas = {r["number"]: (c, r["titulo"]) for r in fechados if (c := classificar(r["reason"]))}
    uniformes = sorted(pr for pr, (c, _) in causas.items() if c == UNIFORME)
    return {"prs": len(causas), "uniformes": uniformes,
            "fracao": round(len(uniformes) / len(causas), 3) if causas else 0.0,
            "tokens_uniformes": sum(tokens_do_item(store, causas[pr][1])[0] for pr in uniformes)}
