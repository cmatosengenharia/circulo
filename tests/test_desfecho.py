"""Desfecho por decisão (circulo/desfecho.py): cada "sim" do Jev ganha depois o que rendeu — PR proposto/entregue, estudo
adotado/contestado, evolução aplicada/revertida — com custo; o aluno treina nesse rótulo; o painel mostra tokens por PR."""
import json
import time
import urllib.request

from circulo import desfecho, intencoes
from circulo.estudo import Estudo

from test_estudo import Pesquisa, pedido, resposta  # noqa: F401
from test_painel import painel  # noqa: F401
from test_self_dev import TEST_CMD, FakeGH, FixAgent, erro_recorrente, repo  # noqa: F401


def _llm(s, papel, tokens, ha=0, entrada=""):
    s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,duracao_ms,ok,erro,entrada,created_at) VALUES(1,?,'m','fixo',?,100,1,NULL,?,?)", (papel, tokens, entrada, time.time() - ha))


def test_tarefa_do_giro_fecha_o_desfecho_da_decisao_de_gastar(circle):
    s = circle.store
    circle.ctx.dl.worth_spending("estudar_pedido", {"est_tokens": 100, "value_signal": 0.9})
    d = s.one("SELECT id FROM decisions WHERE question='worth_spending' ORDER BY id DESC LIMIT 1")
    _llm(s, "estudo", 5000)
    intencoes.executar(s, "estudar_pedido", lambda: 1, motivo="estudo")
    r = s.one("SELECT * FROM desfechos ORDER BY id DESC LIMIT 1")
    assert r["decision_id"] == d["id"] and r["acao"] == "estudar_pedido" and r["resultado"] == "nada" and r["tokens"] == 5000 and r["rendeu"] == 0
    desfecho.atualizar(s, "estudar_pedido", "adotar", item_id=7, tokens=5200)
    r = s.one("SELECT * FROM desfechos ORDER BY id DESC LIMIT 1")
    assert r["resultado"] == "adotar" and r["rendeu"] == 1 and r["item_id"] == 7 and r["tokens"] == 5200
    assert s.one("SELECT COUNT(*) n FROM desfechos")["n"] == 1                          # enriqueceu, não duplicou
    assert desfecho.rotulos(s, "worth_spending") == {d["id"]: "true"}


def test_estudo_e_evolucao_registram_o_veredito(circle):
    s = circle.store
    pedido(circle)
    circle.ctx.dl.llm = Pesquisa(resposta("contestar", urls=("https://a.org/1", "https://b.org/2", "https://c.org/3")), citacoes=["https://a.org/1"])
    Estudo(circle.ctx).run()
    r = s.one("SELECT resultado, rendeu, tokens FROM desfechos WHERE acao='estudar_pedido' ORDER BY id DESC LIMIT 1")
    assert r["resultado"] == "contestar" and r["rendeu"] == 1 and r["tokens"] > 0
    desfecho.evolucao(s, "applied", "regra nova")
    desfecho.registrar(s, "should_evolve", "evoluir", "revertida")
    rs = [x["resultado"] for x in s.q("SELECT resultado FROM desfechos WHERE question='should_evolve' ORDER BY id")]
    assert rs == ["aplicada", "revertida"]


def test_developer_proposto_vira_entregue_quando_o_pr_entra(circle, repo):  # noqa: F811
    from circulo.self_dev import SelfDeveloper, concluir_mergeados
    s = circle.store
    erro_recorrente(circle)
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    r = dev.run_once(autorizado=True)
    assert r.status == "proposto"
    d = s.one("SELECT * FROM desfechos WHERE acao='corrigir_codigo' ORDER BY id DESC LIMIT 1")
    assert d["resultado"] == "proposto" and d["item_id"] == r.item_id and d["pr"] == r.pr and d["rendeu"] == 1
    s.x("UPDATE prs SET status='mergeado' WHERE number=?", (r.pr,))
    concluir_mergeados(s)
    assert s.one("SELECT resultado FROM desfechos WHERE id=?", (d["id"],))["resultado"] == "entregue"
    res = desfecho.resumo(s)
    assert res["hoje"]["por_acao"]["corrigir_codigo"]["entregues"] == 1 and res["hoje"]["prs_mergeados"] == 1


def test_aluno_aprende_com_o_desfecho_quando_ele_existe(circle):
    from circulo import aluno
    s = circle.store
    for _ in range(4):
        circle.ctx.dl.worth_spending("estudar_pedido", {"est_tokens": 100, "value_signal": 0.9})
    ids = [r["id"] for r in s.q("SELECT id FROM decisions WHERE question='worth_spending' AND source='jev' ORDER BY id")]
    s.x("INSERT INTO desfechos(decision_id,question,acao,resultado,tokens,rendeu,created_at,updated_at) VALUES(?,'worth_spending','estudar_pedido','nada',0,0,?,?)", (ids[-1], time.time(), time.time())) if ids else None
    ex = aluno.exemplos_de(s)
    if ids:
        ult = [e for e in ex.get("worth_spending", [])]
        assert ult and ult[-1][1] == "false"                                       # o rótulo medido vence o do Jev


def test_painel_mostra_tokens_por_pr(circle, painel):  # noqa: F811
    j = json.loads(urllib.request.urlopen(painel + "/api/desfechos", timeout=5).read())
    assert "hoje" in j and "tokens_por_pr" in j["hoje"] and "decisoes_com_desfecho" in j
    assert "tokens por PR mergeado" in urllib.request.urlopen(painel + "/loop", timeout=5).read().decode()
