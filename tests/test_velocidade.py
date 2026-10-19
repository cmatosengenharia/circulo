"""Velocidade da autoevolução: o planejador não para por teto fixo, o Indagador não seca e o Vigia não fica mudo.

No Mac (19/10) o loop ficou 10 h sem item novo com 3 perguntas validadas esperando: o teto de 6 itens/dia do
planejador tinha sido atingido às 01:31 e a trava do Vigia, já 'tratada', não agiu de novo em 777 passagens.
"""
import time

from circulo import indagador, planejador as pl, vigia
from circulo.planejador import Planejador

from test_planejador import PlanLLM, preparar
from test_self_dev import repo  # noqa: F401 — fixture do repositório


def _itens_loop(s, n, ha=0):
    agora = time.time() - ha
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'loop','feito','x',?,?,?)",
            (f"v{i}", "d", 700 + i, agora, agora))


def _prs(s, status):
    agora = time.time()
    for i, st in enumerate(status):
        s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (500 + i, 1, f"pr {i}", f"b{i}", st, agora - i, agora - i))


def test_seis_itens_no_dia_nao_param_mais_o_planejador(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    _itens_loop(circle.store, 6)
    assert plan.precisa() and circle.store.get(pl.GATE)["motivo"] is None
    _itens_loop(circle.store, pl.MAX_POR_DIA)
    assert not plan.precisa() and "teto diário" in circle.store.get(pl.GATE)["motivo"]


def test_qualidade_ruim_freia_o_teto(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    _prs(circle.store, ["fechado", "fechado", "mergeado", "fechado"])
    assert plan.teto() == pl.FREIO_POR_DIA
    _itens_loop(circle.store, pl.FREIO_POR_DIA)
    assert not plan.precisa() and "freado" in circle.store.get(pl.GATE)["motivo"]
    circle.store.x("UPDATE prs SET status='mergeado'")
    assert plan.teto() == pl.MAX_POR_DIA and plan.precisa()


def test_fila_vazia_planeja_em_minutos_e_com_item_na_fila_espera_mais(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    s = circle.store
    s.set("planejador", {"em": time.time() - pl.INTERVALO_RAPIDO - 1})
    assert plan.precisa()                                              # fila vazia: 2 min bastam
    agora = time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('a','d','loop','pendente','e',1,?,?)", (agora, agora))
    assert not plan.precisa() and "intervalo" in s.get(pl.GATE)["motivo"]
    s.set("planejador", {"em": time.time() - pl.INTERVALO - 1})
    assert plan.precisa()


def test_sem_developer_o_motivo_fica_registrado(circle):
    assert not Planejador(circle.ctx, None).precisa()
    assert circle.store.get(pl.GATE)["motivo"] == "sem LLM ou sem Developer"


def test_indagador_volta_logo_quando_nao_ha_pergunta_valida(circle):
    s = circle.store
    s.set("indagador", {"loop": time.time() - indagador.INTERVALO_FOME - 1})
    assert indagador.proximo_cerebro(s) is not None                   # sem válida esperando: 30 min, não 6 h
    agora = time.time()
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) VALUES('k','arquiteto','q?','valida','loop',0.5,?,?)",
        (agora, agora))
    assert indagador.proximo_cerebro(s) is None                       # com válida esperando: volta ao intervalo longo


def test_vigia_cita_o_motivo_medido_do_planejador_e_age_de_novo_se_a_trava_persiste(circle):
    s = circle.store
    antes = time.time() - vigia.ESPERA_PERGUNTA - vigia.INTERVALO - 60
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) VALUES('k','arquiteto','q?','valida','loop',0.5,?,?)",
        (antes, antes))
    s.set(pl.GATE, {"em": time.time(), "motivo": "teto diário: 6 itens em 24 h (teto 6)"})
    achado = {a["chave"]: a for a in vigia.sondar(s)}["pergunta_valida_parada"]
    assert "teto diário" in achado["sugestao"] and achado["evidencia"]["planejador_motivo"].startswith("teto")
    agora = time.time()
    s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,item_id,primeira_em,ultima_em,vezes) "
        "VALUES('pergunta_valida_parada','t','{}','s',0.8,'trava','alertar',0.6,'{}','aberta',NULL,?,?,5)", (agora - vigia.REAGIR - 60, agora))
    v = vigia.Vigia(circle.ctx)
    assert "pergunta_valida_parada" in v.rodar()["agiu"]               # trava antiga, ação antiga: age de novo
    assert "pergunta_valida_parada" not in v.rodar()["agiu"]           # e não repete na passagem seguinte
