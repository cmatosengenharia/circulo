"""Entregas de produto sem uso: os PRs de produto mergeados há 7 dias ou mais sem nenhum evento com o nome do
`evento_esperado` gravado no merge depois do `merged_at`. Uso anterior ao merge não conta: é de antes da entrega."""
from __future__ import annotations

from .norte import SEMANA


def entregas_sem_uso(prs: list[dict], eventos: list[dict], agora: float) -> list[dict]:
    """Os PRs de produto (produto, evento_esperado, merged_at) com 7+ dias de merge e nenhum evento (nome, created_at)
    de mesmo nome estritamente depois do merge, na ordem recebida. Pura."""
    usos: dict[str, list[float]] = {}
    for ev in eventos:
        usos.setdefault(ev["nome"], []).append(ev["created_at"])
    return [pr for pr in prs
            if pr["produto"] and agora - pr["merged_at"] >= SEMANA
            and not any(t > pr["merged_at"] for t in usos.get(pr["evento_esperado"], ()))]
