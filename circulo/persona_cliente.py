"""Persona `cliente` do conselho: entrevista no formato Mom Test para cada produto da fábrica.

Técnica portada da skill `mom-test` (https://github.com/wondelai/skills, MIT; ADR 0004 WON-3): pergunte sobre o que
o cliente já fez e já pagou, nunca a opinião dele sobre a ideia ("você usaria?", "quanto pagaria?" mentem por
gentileza). As perguntas nascem por produto registrado na fábrica (kit 'repo'); o Indagador manda cada uma ao Jev no
Noul `mom_test_valida`, e a que pede opinião sobre a ideia é descartada. `regra` é o que o LocalJev responde.
"""
from __future__ import annotations

import re

from .decision import SN, Question, norm

PERSONA = "cliente"
OBJETIVO = "Cliente de um produto da fábrica: o que já faz hoje para resolver o problema e quanto já pagou por isso (Mom Test)"
NOUL = "mom_test_valida"

# opinião sobre a ideia / futuro hipotético: o que o Mom Test proíbe
_OPINIAO = re.compile(r"\b(usaria|pagaria|compraria|gostaria|recomendaria|seria (util|bom|interessante)|"
                      r"o que (voce )?acha|voce acha|achou d[ao] ideia|ideia de|faz sentido|teria interesse|vai usar)\b")
# comportamento passado e dinheiro já gasto: o que o Mom Test pede
_PASSADO = re.compile(r"\b(da ultima vez|ultima vez|ja (pagou|usou|tentou|gastou|fez|resolveu)|quanto (pagou|gastou|custou)|"
                      r"o que (voce )?fez|usa hoje|faz hoje|no ultimo (mes|ano)|como resolveu)\b")

QUESTAO = Question("noul", "A pergunta `candidatas.%d.texto` (persona cliente) pergunta sobre comportamento passado, e não pede opinião sobre a ideia?",
                   SN("pergunta o que o cliente já fez, já usou ou já pagou num caso real recente (ex.: “da última vez que…, o que você fez?”)",
                      "pede opinião ou previsão sobre a ideia ou o produto (ex.: “você usaria…?”, “quanto pagaria?”, “o que acha de…?”)"))


def questao(i: int) -> Question:
    return Question(QUESTAO.kind, QUESTAO.instructions % i, QUESTAO.criteria)


def regra(texto: str) -> float:
    """p de a pergunta passar no Mom Test: opinião sobre a ideia veta; comportamento passado aprova; o resto é dúvida."""
    t = norm(texto)
    if _OPINIAO.search(t):
        return 0.05
    return 0.9 if _PASSADO.search(t) else 0.4


def perguntas(store) -> list:
    """Duas perguntas Mom Test por produto da fábrica, com o registro do produto como evidência."""
    from . import repo_cliente
    from .perguntas import Pergunta
    out = []
    for r in repo_cliente.repos(store):
        p = store.one("SELECT nome, pedido FROM projects WHERE id=?", (r["id"],))
        if p is None:
            continue
        nome, pedido = p["nome"] or f"produto {r['id']}", (p["pedido"] or "")[:120]
        n = len(repo_cliente.pedidos(store, r["id"]))
        ev = {"projeto": r["id"], "pedido": pedido, "pedidos_repo": n, "base": "medido"}
        out.append(Pergunta(f"cliente:{r['id']}:ultima_vez", PERSONA,
                            f"Como cliente de “{nome}”, da última vez que você precisou de {pedido or 'resolver isso'}, o que você fez "
                            "e quanto pagou por isso?", 0.6, ev, custo=1.5, eixo="produto"))
        out.append(Pergunta(f"cliente:{r['id']}:usa_hoje", PERSONA,
                            f"Como cliente de “{nome}”, o que você usa hoje no lugar dele e quanto já gastou com isso no último mês?",
                            0.5, ev, custo=1.5, eixo="produto"))
    return out
