import time

from circulo.status import loop_status, trava


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
    circle.store.set("orcamento_modo", {"modo": "limite"})     # estes testes provam o corte: modo com limite
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


def _pr_com_vereditos(s, pr, vereditos, agora):
    s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(?,?,'aberto',?,?)", (pr, f"PR {pr}", agora, agora))
    for em, r in vereditos:
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'abc',0,?,'{}',?)", (pr, r, em))


def _tarefa(s, titulo, desde):
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES(?,'d','loop','em_andamento','',1,?,?)", (titulo, desde, desde))


def test_status_mostra_a_primeira_trava_com_idade_e_proximo_passo_sem_llm(circle):
    s, agora = circle.store, time.time()
    circle.heartbeat()
    assert trava(s, agora) is None and loop_status(s, agora)["trava"] is None
    _pr_com_vereditos(s, 264, [(agora - 5 * 3600, "checks em andamento: test"), (agora - 3600, "checks em andamento: test")], agora)
    t = trava(s, agora)
    assert (t["tipo"], t["alvo"], t["idade_h"], t["proximo_passo"]) == ("check", "PR #264", 5.0, "aguardar o check")
    assert "checks em andamento" in t["causa"]

    item = _tarefa(s, "Item parado", agora - 8 * 3600)      # a trava mais antiga é a primeira
    _tarefa(s, "Item andando", agora - 60)
    t = trava(s, agora)
    assert (t["tipo"], t["alvo"], t["idade_h"], t["proximo_passo"]) == ("tarefa", f"item #{item}", 8.0, "reabrir a tarefa")
    assert loop_status(s, agora)["trava"] == t
    assert "há 8 h" in t["texto"] and "reabrir a tarefa" in t["texto"]
    assert s.one("SELECT COUNT(*) n FROM llm_calls")["n"] == 0


def test_portao_recusado_escala_ao_developer_e_pr_fechado_nao_trava(circle):
    s, agora = circle.store, time.time()
    _pr_com_vereditos(s, 300, [(agora - 2 * 3600, "checks em andamento: test"),
                              (agora - 3600, "PR do Developer sem teste novo")], agora)
    t = trava(s, agora)
    assert (t["tipo"], t["alvo"], t["idade_h"], t["proximo_passo"]) == ("portao", "PR #300", 1.0, "escalar ao Developer")
    s.x("UPDATE prs SET status='fechado' WHERE number=300")
    assert trava(s, agora) is None
