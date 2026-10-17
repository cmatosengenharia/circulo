import time

from circulo.status import loop_status


def test_sem_batimento_e_desligado(circle):
    s = loop_status(circle.store)
    assert s["estado"] == "desligado" and "circulo run" in s["detalhe"]
    circle.heartbeat()
    assert loop_status(circle.store)["estado"] == "aguardando"
    assert loop_status(circle.store, now=time.time() + 60)["estado"] == "desligado"   # processo morreu


def test_pausado_e_modo_seguro(circle):
    circle.heartbeat()
    circle.set_control(modo_seguro=True)
    assert loop_status(circle.store)["titulo"] == "Rodando em modo seguro"
    circle.set_control(pausado=True)
    assert loop_status(circle.store)["estado"] == "pausado_humano"


def test_pausado_por_orcamento(circle):
    circle.heartbeat()
    circle.ctx.budget.charge(circle.ctx.budget.limit)
    circle.tick()
    s = loop_status(circle.store)
    assert s["estado"] == "pausado_orcamento" and s["retoma_em"] > time.time()


def test_trabalhando_mostra_projeto(circle):
    circle.heartbeat()
    circle._stage("pedido", {"projeto": 1})
    s = loop_status(circle.store)
    assert s["estado"] == "trabalhando" and s["projeto"] == "Finanças da família" and s["etapa"] == "pedido"


def test_desligado_avisa_pedidos_esperando(circle):
    circle.submit("10 uber")
    assert "1 pedido esperando" in loop_status(circle.store)["detalhe"]
