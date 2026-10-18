"""Replay em lote do aprendiz worth_spending (lição #7, lição #8).

Antes, o Jev só aprendia por baldes finos de entradas iguais: com contextos variados quase todo balde tinha
poucos exemplos e 93% das respostas do worth_spending ficavam abaixo de jev_incerto. O replay reaprende com o
agregado das decisões da regra, priorizado pela perda, validado num holdout de 20% e calibrado por temperatura.
"""
import random

from circulo.decision import Decision, LocalJev, Question, _ece, replay_worth, worth_prob
from circulo.evolution import HealthMonitor
from circulo.loop import Circle

ACOES = ("developer_feature", "idle_evolution", "apply_proposal", "llm_fallback", "planejar_roteiro")


class _JevEmDuvidaNoWorth:
    """Jev real que responde 'não sei' (perto de 50%) em todo worth_spending."""
    source = "jev"

    def ask_many(self, state, questions):
        return {k: Decision(k, "noul", 0.52, 0.04, "jev") for k in questions}, 1


def _contextos(n, seed=7):
    rng = random.Random(seed)
    return [(rng.choice(ACOES), {"est_tokens": rng.choice((0, 400, 1500, 6000, 20_000, 60_000)),
                                 "value_signal": round(rng.uniform(0.05, 1.0), 3)}) for _ in range(n)]


def _regra_permite(dl, action, ctx):
    st = {"action": action, "budget_left_ratio": round(dl.budget.left_ratio(), 3), **ctx}
    v = LocalJev().ask_many(st, {"worth_spending": Question("noul", "?")})[0]["worth_spending"].value
    return v >= dl._worth_limiar(st)


def _confianca_media(dl, estados):
    """Confiança que o Jev registraria em cada estado: a do aprendiz se ele decide, senão a dúvida crua."""
    duvida = Decision("worth_spending", "noul", 0.52, 0.04, "jev")
    out = []
    for st in estados:
        d = dl._worth_aprendido(st, duvida, 0.25)
        out.append(d.confidence if d is not None else duvida.confidence)
    return sum(out) / len(out)


def _saude(c):
    h = HealthMonitor(c.ctx).check()
    return h["invariant_violations"], h["correction_rate"]


def test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra(tmp_path):
    """lição #7 / lição #8: em 200 decisões a dúvida cai abaixo de 50%, sem perder concordância nem calibração."""
    c = Circle(tmp_path, jev=_JevEmDuvidaNoWorth())
    dl = c.ctx.dl
    saude_antes = _saude(c)
    ctxs = _contextos(200)
    concorda = 0
    for action, ctx in ctxs:
        g = dl.worth_spending(action, dict(ctx))
        concorda += g.allowed == _regra_permite(dl, action, ctx)

    jev = [r["confidence"] for r in c.store.q(
        "SELECT confidence FROM decisions WHERE question='worth_spending' AND source='jev'")]
    assert len(jev) == 200
    assert sum(conf < 0.25 for conf in jev) / len(jev) < 0.5          # hoje: ~93%

    rep = c.store.get(dl.WORTH_KEY)["replay"]
    assert rep["adotado"] and rep["holdout"] > 0 and rep["passes"] <= 12
    assert rep["concordancia"] >= rep["concordancia_antes"]          # holdout não piora com o replay
    assert rep["ece"] <= 0.10
    assert concorda / 200 >= 0.9                                     # o portão decide como a regra decidiria
    assert _saude(c) == saude_antes                                  # invariantes e correções intactos


def test_replay_sobe_a_confianca_media_sem_cair_a_concordancia(tmp_path):
    c = Circle(tmp_path, jev=_JevEmDuvidaNoWorth())
    dl = c.ctx.dl
    for action, ctx in _contextos(150, seed=1):
        st = {"action": action, "budget_left_ratio": 1.0, **ctx}
        dl._worth_rotular(st, LocalJev().ask_many(st, {"worth_spending": Question("noul", "?")})[0]["worth_spending"])
    sondas = [{"action": a, "budget_left_ratio": 1.0, **ctx} for a, ctx in _contextos(80, seed=99)]
    antes = _confianca_media(dl, sondas)
    rep = dl.worth_replay()
    assert rep["adotado"]
    assert rep["concordancia"] >= rep["concordancia_antes"]
    assert _confianca_media(dl, sondas) > antes + 0.2


def test_replay_nao_infla_confianca_com_rotulos_aleatorios(tmp_path):
    """Anti-inflação: N passes sobre rótulos sem padrão não podem deixar o Jev mais confiante."""
    c = Circle(tmp_path, jev=_JevEmDuvidaNoWorth())
    dl = c.ctx.dl
    rng = random.Random(3)
    for action, ctx in _contextos(200, seed=5):
        v = rng.random()
        dl._worth_rotular({"action": action, "budget_left_ratio": 1.0, **ctx},
                          Decision("worth_spending", "noul", v, abs(2 * v - 1), "local"))
    sondas = [{"action": a, "budget_left_ratio": 1.0, **ctx} for a, ctx in _contextos(80, seed=99)]
    antes = _confianca_media(dl, sondas)
    dl.worth_replay()
    assert _confianca_media(dl, sondas) <= antes + 1e-9


def test_temperatura_nao_muda_a_concordancia():
    rng = random.Random(0)
    ex = []
    for action, ctx in _contextos(120, seed=2):
        st = {"action": action, "budget_left_ratio": 1.0, **ctx}
        permitido = ctx["value_signal"] > 0.5 if rng.random() > 0.1 else ctx["value_signal"] <= 0.5   # 10% de ruído
        ex.append({"features": st, "desfecho": "permitido" if permitido else "negado"})
    m = replay_worth({"pesos": {}, "exemplos": ex})
    modelo = m["modelo"]
    hold = [e for i, e in enumerate(ex) if i % 5 == 4]
    sem_t = {**modelo, "T": 1.0}
    assert [worth_prob(modelo, e["features"]) >= 0.5 for e in hold] == \
           [worth_prob(sem_t, e["features"]) >= 0.5 for e in hold]
    ps = [worth_prob(modelo, e["features"]) for e in hold]
    assert abs(_ece(ps, [int(e["desfecho"] == "permitido") for e in hold]) - m["replay"]["ece"]) < 1e-3
    assert m["replay"]["ece"] <= 0.10
