"""O aluno como decisor: o mesmo contrato do Jev, servido pelo modelo destilado — quando ele provou em sombra.

`AlunoJev` responde uma pergunta com o aluno só se aquela pergunta está "pronta para decidir" (concordância ≥ 95 %
em ≥ 300 palpites) e a confiança do palpite passa o mínimo; senão delega à regra determinística (`LocalJev`). É o
degrau da cascata regra → aluno → Jev → LLM, e o que torna a tese "Jev First" portátil: sem a API do Jev, o loop
continua decidindo com o que aprendeu dele (`CIRCULO_DECISOR=aluno`, ou automaticamente quando não há chave).
"""
from __future__ import annotations

from typing import Any, Mapping

from .aluno import palpite, pronto_para_decidir
from .decision import Decision, LocalJev
from .state import Store

CONF_MIN = 0.7


class AlunoJev:
    source = "local"          # o que o aluno não decide, a regra decide: para o loop, é o decisor de reserva

    def __init__(self, store: Store, reserva: LocalJev | None = None, conf_min: float = CONF_MIN):
        self.s, self.reserva, self.conf_min = store, reserva or LocalJev(), conf_min
        self.respondidas = 0

    def ask_many(self, state: Mapping[str, Any], questions: Mapping[str, Any]) -> tuple[dict[str, Decision], int]:
        out, resto = {}, {}
        for qid, q in questions.items():
            p = None
            try:
                if pronto_para_decidir(self.s, qid):
                    p = palpite(self.s, qid, state)
            except (KeyError, ValueError, TypeError, ZeroDivisionError):   # o aluno nunca derruba a decisão: a regra responde
                p = None
            if p and float(p[1]) >= self.conf_min:
                rot, conf = p
                valor: Any = rot if q.kind == "choice" else (float(rot) if q.kind == "score" else (0.5 + conf / 2 if rot == "true" else 0.5 - conf / 2))
                out[qid] = Decision(qid, q.kind, valor, float(conf), "aluno", {"_aluno": True})
                self.respondidas += 1
            else:
                resto[qid] = q
        if resto:
            r, _ = self.reserva.ask_many(state, resto)
            out.update(r)
        return out, 0


__all__ = ["AlunoJev", "CONF_MIN"]
