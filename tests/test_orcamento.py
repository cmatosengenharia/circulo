"""Limite diário da API customizável pelo painel: vale na hora, tem teto duro e fica registrado."""
import time

from circulo.budget import LIMITE_MIN, definir_limite, limite_diario
from conftest import NOON

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


def test_modo_ilimitado_e_o_padrao_nao_corta_e_continua_medindo(circle):
    from circulo.budget import consumo, definir_modo, modo_orcamento
    b, s = circle.ctx.budget, circle.store
    assert modo_orcamento(s) == "ilimitado" and b.ilimitado
    definir_limite(s, 100_000, b.limit)
    s.x("UPDATE budget SET tokens=0")
    b.charge(250_000, "llm")                                      # bem acima do limite configurado
    assert b.used() == 250_000 and not b.exhausted() and b.can_spend(10 ** 7) and b.left_ratio() == 1.0
    assert circle.tick().pause_reason is None                     # o loop não pausa por orçamento
    assert b.snapshot()["modo"] == "ilimitado" and consumo(s)["hoje"] >= 250_000   # mas a medição está lá (o giro gastou mais um pouco)
    definir_modo(s, "limite")
    assert b.exhausted() and not b.can_spend(1) and b.left_ratio() == 0.0
    assert circle.tick().pause_reason == "orcamento"
    assert (s.get("orcamento_modo") or {})["historico"][-1][1:] == ["ilimitado", "limite"]


def test_consumo_resume_a_medicao_e_sugere_limite_pelo_p90(circle):
    from datetime import timedelta
    from circulo.budget import consumo
    s = circle.store
    hoje, agora = NOON.date(), NOON.timestamp()
    for i, t in enumerate([120_000, 300_000, 180_000, 240_000, 900_000]):          # 5 dias completos + hoje
        s.x("INSERT INTO budget(day,tokens,jev_calls,llm_calls) VALUES(?,?,1,1) ON CONFLICT(day) DO UPDATE SET tokens=excluded.tokens",
            ((hoje - timedelta(days=i + 1)).isoformat(), t))
    s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) VALUES(1,'estudo','m','jev',30000,1,'x',?)", (agora,))
    c = consumo(s, 14, agora)
    assert c["dias_completos"] == 5 and c["mediana_dia"] == 240_000 and c["maximo_dia"] == 900_000
    assert c["sugestao_limite"] == 900_000                            # p90 de 5 dias cai no maior; arredondado em 50 mil
    assert c["por_papel"]["estudo"]["tokens"] == 30000 and sum(c["por_hora"]) == 30000 and len(c["por_dia"]) >= 5
    assert consumo(circle.store, 2, agora)["sugestao_limite"] is None        # com menos de 3 dias completos, não sugere


def test_vigia_no_modo_ilimitado_so_avisa_consumo_alto(circle):
    from datetime import timedelta
    from circulo import vigia
    s = circle.store
    hoje, agora = NOON.date(), NOON.timestamp()
    for i in range(4):
        s.x("INSERT INTO budget(day,tokens,jev_calls,llm_calls) VALUES(?,200000,1,1) ON CONFLICT(day) DO UPDATE SET tokens=200000", ((hoje - timedelta(days=i + 1)).isoformat(),))
    s.x("INSERT INTO budget(day,tokens,jev_calls,llm_calls) VALUES(?,650000,1,1) ON CONFLICT(day) DO UPDATE SET tokens=650000", (hoje.isoformat(),))
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Pedido seu','d','pedido_cassio','pendente','pedido',1,?,?)", (agora, agora))
    chaves = {x["chave"]: x for x in vigia.sondar(s, agora)}
    assert "orcamento_curto" not in chaves                             # sem corte, não há "não paga o próximo estudo"
    assert chaves["consumo_alto"]["gravidade"] == 0.4 and chaves["consumo_alto"]["evidencia"]["mediana_dia"] == 200000


def test_painel_muda_o_modo_e_expoe_o_consumo(circle, painel):  # noqa: F811
    import json
    import urllib.request
    st, j = post(painel + "/api/orcamento", {"modo": "limite"}, {"X-Circulo": "1"})
    assert st == 200 and j["depois"] == "limite"
    assert json.loads(urllib.request.urlopen(painel + "/api/estado", timeout=5).read())["orcamento"]["modo"] == "limite"
    st, j = post(painel + "/api/orcamento", {"modo": "ilimitado"}, {"X-Circulo": "1"})
    assert st == 200 and j["depois"] == "ilimitado"
    c = json.loads(urllib.request.urlopen(painel + "/api/consumo?dias=7", timeout=5).read())
    assert c["modo"] == "ilimitado" and "por_papel" in c and c["dias"] == 7
    assert circle.store.one("SELECT COUNT(*) n FROM alerts WHERE kind='controle' AND message LIKE '%modo%'")["n"] == 2


def test_marcos_do_orcamento_ficam_mudos_no_modo_ilimitado(circle):
    from circulo.orcamento_dia import avisar_marcos
    b = circle.ctx.budget
    b.charge(b.limit)
    avisos = []
    assert avisar_marcos(circle.store, b, lambda m, k: avisos.append(m)) is None and avisos == []
