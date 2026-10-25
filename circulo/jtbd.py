"""O agrupador de jobs ligado ao loop: no idle, cada job com ≥3 pedidos em 7 dias vira a missão 'antecipar:<job>' e
exatamente 1 proposta antecipada no roteiro, presa à última pergunta do entrevistador_jtbd (lição #15). Os pedidos
vêm dos eventos (job gravado) e dos itens 'pedido_cassio' do roteiro (job pelas palavras-chave do texto)."""
from __future__ import annotations

from . import antecipacao, jobs

PERSONA = "entrevistador_jtbd"


def pergunta_de_origem(store) -> int | None:
    r = store.one("SELECT id FROM perguntas WHERE persona=? ORDER BY id DESC LIMIT 1", (PERSONA,))
    return r["id"] if r else None


def _fontes(store, agora: float | None) -> tuple:
    return None, antecipacao.pedidos_roteiro(store, agora)     # None: os eventos, lidos pelo próprio jobs


def propor(store, agora: float | None = None) -> list[int]:
    """Uma proposta por job recorrente ainda sem item na semana; sem pergunta do conselho, nenhuma (idempotente)."""
    pid = pergunta_de_origem(store)
    criadas = []
    for pedidos in _fontes(store, agora) if pid is not None else ():
        while (rid := jobs.propor_item(store, pid, agora, pedidos)) is not None:
            criadas.append(rid)
    return criadas


def precisa(store) -> bool:
    return jobs.precisa(store) or (pergunta_de_origem(store) is not None
                                   and any(jobs.sem_proposta(store, None, p) for p in _fontes(store, None)))


def diagnostico(store, agora: float | None = None) -> dict:
    """O maior grupo de job nas mesmas fontes que o gerador agrupa (cada uma separada) e o que impede a proposta."""
    fontes = [jobs.pedidos_7d(store, agora) if p is None else p for p in _fontes(store, agora)]
    grupos = [antecipacao.maior_grupo(p) for p in fontes]
    maior, classificados = max(m for m, _ in grupos), sum(c for _, c in grupos)
    tem_pergunta = pergunta_de_origem(store) is not None
    motivo = antecipacao.motivo_sem_proposta(sum(map(len, fontes)), classificados, maior, tem_pergunta)
    if not motivo:
        motivo = ("proposta pendente: o idle 'antecipar' ainda não rodou"
                  if any(jobs.sem_proposta(store, agora, p) for p in fontes)
                  else "o job já tem proposta aberta de antes dos 7 dias")
    return {"job_maior_grupo": maior, "motivo_sem_proposta": motivo}


def antecipar(store, agora: float | None = None) -> dict[str, list[int]]:
    return {"missoes": jobs.antecipar(store, agora), "propostas": propor(store, agora)}
