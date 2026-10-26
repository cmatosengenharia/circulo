"""Portão de pedido (pergunta do conselho #323): antes da LLM, o pedido do Developer cita critério de aceite, arquivo
alvo (.py) e resultado esperado? Se falta algum, sai UMA pergunta de esclarecimento, a do primeiro campo ausente. Por
ora só mede: o veredito fica em `pedidos_claros` e o Developer segue igual."""
import time

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo.custo import tokens_por_veredito
from circulo.pedido_claro import (ARQUIVO, CRITERIO, PERGUNTAS, RESULTADO, avaliar, fracao_incompletos,
                                  itens_com_veredito, registrar)
from circulo.perguntas import METRICAS

COMPLETO = ("Criar função pura em circulo/pedido_claro.py; teste de regressão com pedidos completos, incompletos e "
            "vazios.\nSucesso: veredito calculado em 100% dos pedidos")


def test_pedido_completo_nao_pergunta_nada():
    v = avaliar("Portão de pedido", COMPLETO)
    assert v.completo and v.faltando == () and v.pergunta is None


def test_cada_campo_ausente_vira_a_pergunta_dele():
    sem_criterio = "Mudar circulo/loop.py.\nSucesso: giro mais rápido"
    sem_arquivo = "Teste de regressão cobre o giro.\nSucesso: giro mais rápido"
    sem_resultado = "Mudar circulo/loop.py; teste de regressão cobre o giro."
    assert avaliar("x", sem_criterio).faltando == (CRITERIO,)
    assert avaliar("x", sem_arquivo).faltando == (ARQUIVO,)
    v = avaliar("x", sem_resultado)
    assert v.faltando == (RESULTADO,) and v.pergunta == PERGUNTAS[RESULTADO]


def test_pedido_vazio_falta_tudo_e_pergunta_so_o_primeiro():
    for titulo, detalhe in (("", ""), (None, None), ("   ", "\n")):
        v = avaliar(titulo, detalhe)
        assert v.faltando == (CRITERIO, ARQUIVO, RESULTADO) and v.pergunta == PERGUNTAS[CRITERIO]
    assert avaliar("", "Mudar circulo/loop.py").pergunta == PERGUNTAS[CRITERIO]
    assert avaliar("", "teste em tests/test_loop.py").faltando == (RESULTADO,)   # caminho em tests/ também é alvo


def test_registrar_guarda_o_veredito_e_mede_a_fracao(circle):
    s = circle.store
    assert fracao_incompletos(s) is None
    registrar(s, {"id": 1, "titulo": "a", "detalhe": COMPLETO})
    registrar(s, {"id": 2, "titulo": "b", "detalhe": ""})
    assert fracao_incompletos(s) == 0.5
    linha = s.one("SELECT item, completo, faltando, pergunta FROM pedidos_claros WHERE item=2")
    assert (linha["completo"], linha["faltando"], linha["pergunta"]) == (0, "criterio,arquivo,resultado", PERGUNTAS[CRITERIO])


def test_developer_registra_o_veredito_e_nao_bloqueia(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    agent = ZipAgent(conserta_na=1)
    dev, _ = dev_de(circle, repo, tmp_path, agent)
    dev.run_once()
    linha = circle.store.one("SELECT item, completo FROM pedidos_claros")
    assert linha["item"] == item["id"] and agent.tasks                # o agente rodou mesmo com o pedido avaliado


def test_tokens_por_pr_somados_por_veredito_do_portao(circle):
    """Pergunta #327: tokens/PR de pedido incompleto contra completo, em número e não só prevenido."""
    s, agora = circle.store, time.time()
    for titulo, detalhe, status in (("Completo entregue", COMPLETO, "feito"), ("Completo travado", COMPLETO, "bloqueado"),
                                    ("Vago entregue", "melhorar o loop", "feito"), ("Vago entregue 2", "", "feito"),
                                    ("Sem veredito", COMPLETO, "feito")):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES(?,?,'erro',?,'',1,?,?)", (titulo, detalhe, status, agora, agora))
        if titulo != "Sem veredito":
            registrar(s, dict(s.one("SELECT * FROM roadmap WHERE titulo=?", (titulo,))), agora=agora)
    for entrada, tokens, quando in (("Completo entregue", 30_000, agora), ("reparo: Completo entregue", 10_000, agora),
                                    ("Completo travado", 20_000, agora), ("Vago entregue", 70_000, agora),
                                    ("conserto do PR #9: Vago entregue 2", 50_000, agora),
                                    ("Vago entregue 2", 999_999, agora - 2 * 86400), ("Sem veredito", 5_000, agora)):
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) "
            "VALUES(1,'developer','Claude Code','fixo',?,1,?,?)", (tokens, entrada, quando))
    r = tokens_por_veredito(s.q("SELECT entrada, tokens FROM llm_calls WHERE created_at>=?", (agora - 86400,)),
                            itens_com_veredito(s))
    assert r["por_veredito"] == {"completo": {"tokens": 60_000, "prs": 1, "tokens_por_pr": 60_000},
                                 "incompleto": {"tokens": 120_000, "prs": 2, "tokens_por_pr": 60_000},
                                 "sem_veredito": {"tokens": 5_000, "prs": 1, "tokens_por_pr": 5_000}}
    assert r["razao_incompleto_completo"] == 1.0 and r["prs_sem_veredito"] == 1
    assert tokens_por_veredito([], [])["razao_incompleto_completo"] is None
    _, ctx = METRICAS["tokens_por_pr"][1](s, agora)
    assert ctx["por_veredito"] == r["por_veredito"]                  # publicada na métrica que a pergunta #327 lê


def test_item_sem_veredito_previo_recebe_veredito_ao_ser_escalado(circle, repo, tmp_path):  # noqa: F811
    """Pergunta #331: 27 de 38 PRs sem veredito (itens entregues antes do portão ou sem passar pelo pick). Ao escalar o
    Developer, o item com PR ainda sem veredito é avaliado pelo texto, com a hora do próprio item."""
    s, antes = circle.store, time.time() - 3 * 86400
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES('Entregue antes do portão','melhorar o loop','loop','feito','',1,?,?)", (antes, antes))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,created_at,updated_at) "
        "VALUES(7,1,'Entregue antes do portão','b','mergeado',(SELECT id FROM roadmap WHERE titulo=?),?,?)",
        ("Entregue antes do portão", antes, antes))
    item = erro_recorrente(circle)
    dev, _ = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    dev.run_once()
    vereditos = {r["titulo"]: r["veredito"] for r in itens_com_veredito(s)}
    assert vereditos["Entregue antes do portão"] == "incompleto" and vereditos[item["titulo"]] is not None
    r = tokens_por_veredito([{"entrada": "Entregue antes do portão", "tokens": 1_000}], itens_com_veredito(s))
    assert r["prs_sem_veredito"] == 0 and r["por_veredito"]["incompleto"]["prs"] == 1
    assert s.one("SELECT p.created_at FROM pedidos_claros p JOIN roadmap r ON r.id=p.item "
                 "WHERE r.titulo='Entregue antes do portão'")["created_at"] == antes   # não infla a fração das 24 h
