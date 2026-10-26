"""Portão de pedido (pergunta do conselho #323): antes da LLM, o pedido do Developer cita critério de aceite, arquivo
alvo (.py) e resultado esperado? Se falta algum, sai UMA pergunta de esclarecimento, a do primeiro campo ausente. Por
ora só mede: o veredito fica em `pedidos_claros` e o Developer segue igual."""
from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo.pedido_claro import ARQUIVO, CRITERIO, PERGUNTAS, RESULTADO, avaliar, fracao_incompletos, registrar

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
