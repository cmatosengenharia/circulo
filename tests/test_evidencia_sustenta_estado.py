"""Pergunta do conselho #33 (economista): o Jev decidia `evidencia_sustenta` com dúvida (a regra decidiu 35% de 20 vezes
em 24 h, confiança média 0,36) porque o estado só tinha contagens de fontes. O loop já mede o teste citado no main
(licoes.checagens: exit code e execuções seguidas); agora isso entra no estado, em faixas, com a alternância
(passa-falha-passa), que é o sinal de teste instável."""
import json
import time

from circulo import jev_lab
from circulo.decision import LocalJev, Question
from circulo.estudo import Estudo

NODE = "tests/test_x.py::test_y"
BASE = {"veredito": "adaptar", "n_fontes": 3, "n_achados": 4, "n_citacoes": 2, "justificativa": "as fontes medem outra coisa"}


def _licao(store, exits, node=NODE):
    agora = time.time()
    checagens = [{"sha": f"s{i}", "exit": e, "tick": i, "em": agora + i} for i, e in enumerate(exits)]
    store.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,created_at,updated_at,node_id,checagens) "
            "VALUES(?,?,?,?,'aberta',1,0,?,?,?,?)", (f"teste:{node}", "developer:testes", "trabalho", "x", agora, agora, node, json.dumps(checagens)))


def _regra_antiga(s):
    p = min(1.0, int(s["n_fontes"]) / 3) * (0.9 if int(s["n_citacoes"]) else 0.6)
    return p if s["veredito"] == "contestar" else min(1.0, p + 0.15)


def _estados(circle):
    s = circle.store
    _licao(s, [1], "tests/test_a.py::test_falhou")
    _licao(s, [1, 0], "tests/test_a.py::test_passou_1x")
    _licao(s, [0, 0], "tests/test_a.py::test_passou_2x")
    _licao(s, [0, 0, 0, 0], "tests/test_a.py::test_passou_4x")
    _licao(s, [0, 1, 0], "tests/test_a.py::test_alterna")
    _licao(s, [4], "tests/test_a.py::test_sumiu")
    textos = {"sem_teste": "melhorar o cache", "falhou": "teste tests/test_a.py::test_falhou",
              "passou_1x": "teste tests/test_a.py::test_passou_1x", "passou_2x": "teste tests/test_a.py::test_passou_2x",
              "passou_4x": "teste tests/test_a.py::test_passou_4x", "alterna": "teste tests/test_a.py::test_alterna",
              "sumiu": "teste tests/test_a.py::test_sumiu", "sem_medicao": "teste tests/test_a.py::test_nunca_rodou"}
    return {k: jev_lab.estado_evidencia(s, t, BASE) for k, t in textos.items()}


def test_estado_traz_o_teste_citado_em_faixas(circle):
    st = _estados(circle)
    assert {k: (v["teste_citado"], v["exit_main"], v["execucoes_seguidas"], v["alternou"]) for k, v in st.items()} == {
        "sem_teste": ("nenhum", "sem_execucao", "0", False),
        "falhou": ("existe", "falhou", "1", False),
        "passou_1x": ("existe", "passou", "1", False),
        "passou_2x": ("existe", "passou", "2", False),
        "passou_4x": ("existe", "passou", "3+", False),
        "alterna": ("existe", "passou", "1", True),
        "sumiu": ("nao_existe", "nao_coletado", "1", False),
        "sem_medicao": ("nao_medido", "sem_execucao", "0", False)}
    assert all(set(BASE.items()) <= set(v.items()) for v in st.values())     # o que já ia ao Jev continua indo


def test_estados_distintos_dao_confiancas_distintas_e_a_decisao_da_regra(circle):
    st = _estados(circle)
    q = Question("noul", "?")
    for veredito, fontes, citacoes in (("adaptar", 3, 2), ("contestar", 3, 0), ("contestar", 1, 0), ("adaptar", 2, 1)):
        base = {**BASE, "veredito": veredito, "n_fontes": fontes, "n_citacoes": citacoes}
        ds = {k: LocalJev().ask_many({**v, **base}, {"evidencia_sustenta": q})[0]["evidencia_sustenta"] for k, v in st.items()}
        assert all((float(d.value) >= 0.5) == (_regra_antiga(base) >= 0.5) for d in ds.values()), (base, ds)
        quatro = [ds[k].confidence for k in ("sem_teste", "falhou", "passou_1x", "passou_2x")]
        assert len(set(quatro)) == 4, (base, quatro)
        assert ds["passou_4x"].confidence >= ds["passou_2x"].confidence > ds["passou_1x"].confidence
        assert ds["alterna"].confidence < ds["passou_1x"].confidence                       # alternância = instável


def test_estudo_manda_ao_jev_o_resultado_medido_do_teste_citado(circle):
    from test_estudo import Pesquisa, resposta
    _licao(circle.store, [0, 0])
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES(?,?,'pedido_cassio','pendente','pedido pelo painel',500,0,0)", ("Trocar o cache", f"o teste {NODE} cobre isso"))
    circle.ctx.dl.llm = Pesquisa(resposta("adaptar"), citacoes=["https://c.org/z"])
    visto = {}
    original = circle.ctx.dl.ask

    def espiao(name, q, state):
        visto[name] = (q, dict(state))
        return original(name, q, state)
    circle.ctx.dl.ask = espiao
    Estudo(circle.ctx).run()
    q, st = visto["evidencia_sustenta"]
    assert (st["teste_citado"], st["exit_main"], st["execucoes_seguidas"], st["alternou"]) == ("existe", "passou", "2", False)
    assert "`execucoes_seguidas`" in q.criteria["true"] and "`alternou`" in q.criteria["false"]
