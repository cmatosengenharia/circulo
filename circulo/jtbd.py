"""O agrupador de jobs ligado ao loop: no idle, cada job com ≥3 pedidos em 7 dias vira a missão 'antecipar:<job>' e
exatamente 1 proposta antecipada no roteiro, presa à última pergunta do entrevistador_jtbd (lição #15)."""
from __future__ import annotations

from . import jobs

PERSONA = "entrevistador_jtbd"


def pergunta_de_origem(store) -> int | None:
    r = store.one("SELECT id FROM perguntas WHERE persona=? ORDER BY id DESC LIMIT 1", (PERSONA,))
    return r["id"] if r else None


def propor(store, agora: float | None = None) -> list[int]:
    """Uma proposta por job recorrente ainda sem item na semana; sem pergunta do conselho, nenhuma (idempotente)."""
    pid = pergunta_de_origem(store)
    criadas = []
    while pid is not None and (rid := jobs.propor_item(store, pid, agora)) is not None:
        criadas.append(rid)
    return criadas


def precisa(store) -> bool:
    return jobs.precisa(store) or (pergunta_de_origem(store) is not None and bool(jobs.sem_proposta(store)))


def antecipar(store, agora: float | None = None) -> dict[str, list[int]]:
    return {"missoes": jobs.antecipar(store, agora), "propostas": propor(store, agora)}
