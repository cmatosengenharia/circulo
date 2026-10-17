import pytest

from circulo import finance
from circulo.money import find_amount, fmt_brl, parse_brl
from conftest import say


@pytest.mark.parametrize("txt,cents", [
    ("38,90", 3890), ("38,9", 3890), ("38.90", 3890), ("1.234,56", 123456),
    ("5.000", 500000), ("38", 3800), ("0,01", 1), ("R$ 10,00", 1000),
])
def test_parse_brl(txt, cents):
    assert parse_brl(txt) == cents
    assert isinstance(parse_brl(txt), int)


def test_parse_rejects():
    with pytest.raises(ValueError):
        parse_brl("abc")
    with pytest.raises(ValueError):
        parse_brl("-5")


def test_find_and_fmt():
    assert find_amount("38,90 ifood almoço") == (3890, "ifood almoço")
    assert find_amount("ifood 38,90 almoço") == (3890, "ifood almoço")
    assert find_amount("sem valor") is None
    assert fmt_brl(123456) == "R$ 1.234,56"
    assert fmt_brl(-5) == "-R$ 0,05"
    with pytest.raises(TypeError):
        fmt_brl(1.5)


def test_snapshot_from_reference_situation(circle):
    s = finance.snapshot(circle.store)
    assert s.patrimonio_liquido_cents == 6_000_000 + 60_000_000 - 14_800_000
    assert s.progresso_bp == (51_200_000 * 10_000) // 85_000_000
    say(circle, "+5000 salário")
    say(circle, "1000 mercado epa")
    s = finance.snapshot(circle.store)
    assert s.sobra_mes_cents == 400_000
    assert s.meses_ate_meta == -(-(85_000_000 - (51_200_000 + 400_000)) // 400_000)
    assert finance.check_invariants(circle.store) == []


def test_invariant_violation_undoes_insert(circle):
    b = finance.base(circle.store)
    circle.store.set("patrimonio_base", {**b, "reserva_cents": -1})
    _, [r] = say(circle, "10 mercado epa")
    assert r.errors
    assert circle.store.one("SELECT COUNT(*) c FROM ledger")["c"] == 0
