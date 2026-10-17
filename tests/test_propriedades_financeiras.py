"""Evidência reforçada para código de dinheiro: propriedades testadas em muitos casos aleatórios.

No CI comum roda com poucos casos; no job "Evidência reforçada" roda com CIRCULO_PROP_N=5000.
É isso que permite ao loop alterar finance.py/money.py sozinho, sem aprovação humana.
"""
import os
import random
from datetime import datetime

import pytest

from circulo import finance
from circulo.budget import TZ
from circulo.money import find_amount, fmt_brl, parse_brl

N = int(os.environ.get("CIRCULO_PROP_N", "200"))
SEED = int(os.environ.get("CIRCULO_PROP_SEED", "20261017"))


def brl_text(rnd, cents):
    reais, c = divmod(cents, 100)
    estilo = rnd.choice(["virgula", "ponto", "milhar", "inteiro"])
    if estilo == "inteiro" and c == 0:
        return str(reais)
    if estilo == "ponto" and reais < 1000:
        return f"{reais}.{c:02d}"
    if estilo == "milhar" and reais >= 1000:
        return f"{reais:,}".replace(",", ".") + f",{c:02d}"
    return f"{reais},{c:02d}"


def test_parse_e_formatacao_sao_inversos():
    rnd = random.Random(SEED)
    for _ in range(N):
        cents = rnd.randint(1, 10**9)
        assert parse_brl(brl_text(rnd, cents)) == cents
        s = fmt_brl(cents)
        assert parse_brl(s) == cents and isinstance(parse_brl(s), int)


def test_valor_e_achado_em_qualquer_posicao_do_texto():
    rnd = random.Random(SEED + 1)
    palavras = ["ifood", "mercado", "almoço", "posto", "uber", "farmácia"]
    for _ in range(N):
        cents = rnd.randint(1, 10**7)
        txt = brl_text(rnd, cents)
        ps = rnd.sample(palavras, 2)
        frase = rnd.choice([f"{txt} {ps[0]} {ps[1]}", f"{ps[0]} {txt} {ps[1]}", f"{ps[0]} {ps[1]} {txt}"])
        achado = find_amount(frase)
        assert achado and achado[0] == cents and txt not in achado[1]


@pytest.mark.parametrize("rodada", range(max(1, N // 100)))
def test_invariantes_sob_lancamentos_aleatorios(tmp_path, rodada):
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    rnd = random.Random(SEED + 100 + rodada)
    c = Circle(tmp_path / f"r{rodada}", jev=LocalJev(), now=lambda: datetime.now(TZ))
    esperado_d = esperado_r = 0
    for _ in range(40):
        cents = rnd.randint(1, 500_000)
        if rnd.random() < 0.15:
            c.submit("+" + fmt_brl(cents).replace("R$ ", "") + " salário")
            esperado_r += cents
        else:
            c.submit(fmt_brl(cents).replace("R$ ", "") + " " + rnd.choice(["ifood", "mercado epa", "posto", "loja xyz"]))
            esperado_d += cents
        r = c.tick()
        assert not r.errors, r.errors
    assert finance.check_invariants(c.store) == []
    tot = c.store.one("SELECT COALESCE(SUM(CASE WHEN kind='despesa' THEN amount_cents END),0) d, "
                      "COALESCE(SUM(CASE WHEN kind='receita' THEN amount_cents END),0) r FROM ledger")
    assert (tot["d"], tot["r"]) == (esperado_d, esperado_r)        # nenhum centavo criado ou perdido
    s = finance.snapshot(c.store)
    b = finance.base(c.store)
    assert s.reserva_cents == b["reserva_cents"] + esperado_r - esperado_d
