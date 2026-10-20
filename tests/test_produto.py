"""Produto: giros em paralelo na mesma missão (torneio de variantes) e missões que se conhecem sob o seu controle."""
from circulo.llm import LLMResult

from test_engine import LANDING_V1, LANDING_V2, FakeGen, motor  # noqa: F401 — fixture do motor
from test_painel import painel, post  # noqa: F401


class Variantes(FakeGen):
    """O Builder devolve uma versão fraca para um ângulo e a forte para outro: o torneio tem de escolher a forte."""

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        if "Builder" in system and "Ângulo desta variante" in prompt:
            self.calls.append(("Builder-variante", model, 0))
            forte = "formulário" in prompt.lower()
            return LLMResult(LANDING_V2 if forte else LANDING_V1, 2000, model)
        return super().generate(system=system, prompt=prompt, model=model, max_tokens=max_tokens, web_search=web_search)


def test_giros_em_paralelo_disputam_torneio_e_fica_a_melhor(motor):  # noqa: F811
    c, _, pid = motor
    gen = Variantes()
    c.ctx.dl.llm = gen                                                # o motor usa a LLM do decisor
    c.engine.cycle(pid)                                               # pesquisa + régua
    c.store.x("UPDATE projects SET paralelo=3 WHERE id=?", (pid,))
    r = c.engine.cycle(pid)
    assert r.fase == "construcao" and r.aceita
    assert sum(1 for x in gen.calls if x[0] == "Builder-variante") == 3          # 3 variantes em paralelo
    assert "3 giros em paralelo" in r.nota
    assert "Prova social" in c.engine.current(pid)["content"]                   # a melhor venceu


def test_paralelo_e_limitado_pelo_orcamento(motor):  # noqa: F811
    c, _, pid = motor
    c.store.set("orcamento_modo", {"modo": "limite"})     # estes testes provam o corte: modo com limite
    p = dict(c.store.one("SELECT * FROM projects WHERE id=?", (pid,)))
    p["paralelo"] = 4
    assert c.engine.giros_paralelos(p) == 4
    c.store.x("UPDATE budget SET tokens=?", (c.ctx.budget.limit - 9000,))
    assert c.engine.giros_paralelos(p) == 1                                     # não cabe: um giro só


def test_ligacao_humana_vale_acima_do_jev(motor):  # noqa: F811
    c, gen, pid = motor
    c.submit_project("Crie um portal admin para fotógrafo")
    c.tick()
    outro = c.store.one("SELECT id FROM projects WHERE id!=? AND kit='geral' ORDER BY id DESC", (pid,))["id"]
    c.graph.ligar(pid, outro, "nenhuma")                                        # você separou
    c.graph.conectar(pid)                                                        # o Jev reavalia
    r = c.store.one("SELECT relacao, origem FROM links WHERE a=? AND b=?", tuple(sorted((pid, outro))))
    assert (r["relacao"], r["origem"]) == ("nenhuma", "humano")
    c.graph.ligar(pid, outro, "complementa")
    assert [x["id"] for x in c.graph.ligadas(pid)] == [outro]
    assert "Missões relacionadas" in "Missões relacionadas" and c.graph.contexto(pid)


def test_api_de_produto(motor, monkeypatch):  # noqa: F811
    from circulo.painel import serve
    c, _, pid = motor
    srv = serve(c.store.path, port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, r = post(base + "/api/missao/paralelo", {"id": pid, "n": 2}, {"X-Circulo": "1"})
        assert code == 200 and c.store.one("SELECT paralelo FROM projects WHERE id=?", (pid,))["paralelo"] == 2
        assert post(base + "/api/missao/paralelo", {"id": pid, "n": 9}, {"X-Circulo": "1"})[0] == 400
        c.submit_project("Crie um portal admin para fotógrafo")
        c.tick()
        outro = c.store.one("SELECT id FROM projects WHERE id!=? AND kit='geral' ORDER BY id DESC", (pid,))["id"]
        code, r = post(base + "/api/ligacoes", {"a": pid, "b": outro, "relacao": "complementa"}, {"X-Circulo": "1"})
        assert code == 200 and r["relacao"] == "complementa"
        from circulo.painel import estado
        e = estado(c.store, pid)
        assert e["conexoes"][0]["origem"] == "humano" and e["projeto"]["paralelo"] == 2
        assert post(base + "/api/ligacoes", {"a": pid, "b": pid, "relacao": "complementa"}, {"X-Circulo": "1"})[0] == 400
    finally:
        srv.shutdown()
