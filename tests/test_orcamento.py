"""Limite diário da API customizável pelo painel: vale na hora, tem teto duro e fica registrado."""
import time

from circulo.budget import LIMITE_MIN, definir_limite, limite_diario

from test_painel import painel, post  # noqa: F401 — fixture do servidor do painel


def test_limite_customizado_vale_para_o_porteiro_do_gasto(circle):
    b = circle.ctx.budget
    padrao = b.limit
    definir_limite(circle.store, 500_000, padrao)
    assert b.limit == 500_000
    circle.store.x("UPDATE budget SET tokens=300000")
    b._row()
    assert b.left_ratio() > 0.3                                      # com 200 mil teria acabado
    definir_limite(circle.store, None, padrao)
    assert b.limit == padrao


def test_limite_tem_piso_e_teto(circle):
    import pytest
    from circulo.policy import HARD_DAILY_TOKEN_CAP
    with pytest.raises(ValueError):
        definir_limite(circle.store, LIMITE_MIN - 1, 200_000)
    with pytest.raises(ValueError):
        definir_limite(circle.store, HARD_DAILY_TOKEN_CAP + 1, 200_000)
    circle.store.set("orcamento_limite", {"limite": 10 ** 12})       # valor adulterado direto no banco
    assert limite_diario(circle.store, 200_000) == HARD_DAILY_TOKEN_CAP


def test_painel_muda_o_limite_com_registro(circle, painel):  # noqa: F811
    code, r = post(painel + "/api/orcamento", {"limite": 400000}, {"X-Circulo": "1"})
    assert code == 200 and r["depois"] == 400000 and r["customizado"]
    assert circle.store.one("SELECT message FROM alerts WHERE kind='controle' ORDER BY id DESC LIMIT 1")["message"] \
        .startswith("Você mudou o limite diário da API")
    assert post(painel + "/api/orcamento", {"limite": 5}, {"X-Circulo": "1"})[0] == 400
    assert post(painel + "/api/orcamento", {"limite": 400000})[0] == 403          # sem o cabeçalho do painel
    from circulo.painel import estado
    assert estado(circle.store)["orcamento"]["limite"] == 400000
    code, r = post(painel + "/api/orcamento", {"limite": None}, {"X-Circulo": "1"})
    assert code == 200 and not r["customizado"]


def test_confianca_usa_o_limite_escolhido(circle):
    from circulo.confianca import confianca
    circle.tick()
    circle.store.set("batimento", {"em": time.time(), "pid": 1})
    definir_limite(circle.store, 1_000_000, circle.ctx.budget.limit)
    c = {x["id"]: x for x in confianca(circle.store)["checks"]}["orcamento"]
    assert "1.000.000" in c["valor"]
