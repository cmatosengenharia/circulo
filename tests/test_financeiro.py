from datetime import datetime

import pytest

from circulo.budget import TZ
from circulo.perguntas import _m_lancamentos


def _lancar(s, n: int, meses: int, origem: str | None = None) -> None:
    for i in range(n):
        em = datetime(2026, 9 + i % meses, 1 + i % 28, 12, tzinfo=TZ).timestamp()
        eid = s.enqueue("mensagem", {"text": f"gasto {i}", "at": em, **({"origem": origem} if origem else {})})
        s.x("INSERT INTO ledger(event_id,kind,amount_cents,description,category,tag,confidence,auto_accepted,"
            "policy_version,created_at) VALUES(?,'despesa',1000,?,'mercado','necessario',1.0,1,1,?)", (eid, f"gasto {i}", em))


@pytest.mark.parametrize("n,meses,faltam", [(0, 1, (30, 1)), (10, 1, (20, 0)), (10, 2, (20, 0)),
                                            (30, 1, (0, 0)), (30, 2, (0, 0))])
def test_lancamentos_diz_quanto_falta_para_a_primeira_pergunta(circle, n, meses, faltam):
    """Pergunta #696: 'lancamentos' era 1.0 sem dizer quantos lançamentos e meses faltam para o gasto por categoria."""
    _lancar(circle.store, n, meses)
    valor, ev = _m_lancamentos(circle.store, None)
    assert (ev["reais"], ev["minimo_lancamentos"], ev["minimo_meses"]) == (n, 30, 1)
    assert (ev["faltam_lancamentos"], ev["faltam_meses"]) == faltam
    assert ev["meses"] == (min(n, meses) if n else 0)
    assert valor == (1.0 if n == 0 else max(0.0, 1 - n / 30))


def test_lancamentos_sinteticos_do_demo_nao_contam_como_reais(circle):
    _lancar(circle.store, 30, 1, origem="demo")
    valor, ev = _m_lancamentos(circle.store, None)
    assert ev["lancamentos"] == 30 and ev["reais"] == 0
    assert (ev["faltam_lancamentos"], ev["faltam_meses"], valor) == (30, 1, 1.0)
