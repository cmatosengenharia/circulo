import io
import json

from circulo.decision import Decision, JevHttpClient, LocalJev, Question
from circulo.loop import Circle


class FakeLLM:
    def __init__(self, answer="mercado"):
        self.calls = 0
        self.answer = answer

    def complete(self, system, prompt, max_tokens):
        self.calls += 1
        return self.answer, 300


def test_worth_spending_bloqueia_acima_do_orcamento(circle):
    dl = circle.ctx.dl
    assert dl.worth_spending("idle_evolution", {"est_tokens": 0, "value_signal": 0.6}).allowed
    g = dl.worth_spending("developer_feature", {"est_tokens": 10_000_000, "value_signal": 1.0})
    assert not g.allowed and "orçamento" in g.reason


def test_llm_so_entra_quando_jev_inseguro(tmp_path, clock):
    llm = FakeLLM("mercado")
    c = Circle(tmp_path, jev=LocalJev(), llm=llm, now=clock)
    q = Question("choice", "cat", {k: k for k in c.ctx.policy["categories"]})
    d = c.ctx.dl.choose("category", q, {"description": "ifood", "regras": c.ctx.policy["rules"]})
    assert d.value == "delivery" and d.source == "local" and llm.calls == 0
    d = c.ctx.dl.choose("category", q, {"description": "sacolão do bairro", "regras": c.ctx.policy["rules"]})
    assert d.value == "mercado" and d.source == "llm" and llm.calls == 1
    assert c.ctx.budget.snapshot()["chamadas_llm"] == 1


def test_resposta_invalida_do_jev_cai_no_local(circle):
    class Liar:
        source = "jev"

        def ask_many(self, state, questions):
            return {k: Decision(k, "choice", "inventado", 0.99, "jev") for k in questions}, 10

    circle.ctx.dl.jev = Liar()
    q = Question("choice", "x", {"despesa": "", "receita": "", "correcao": "", "confirmacao": "", "desconhecido": ""})
    d = circle.ctx.dl.ask("input_type", q, {"text": "38 ifood", "has_amount": True})
    assert d.value == "despesa" and d.source == "local"


def test_jev_http_monta_request_da_api(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers["Authorization"]
        seen["body"] = json.loads(req.data)
        resp = {"model": "jev-1", "usage": {"input_tokens": 120}, "answers": {
            "c": {"type": "choice", "choice": "b", "confidence": 0.9, "probabilities": {"a": 0.1, "b": 0.9}},
            "n": {"type": "noul", "noul": 0.8}}}
        return io.BytesIO(json.dumps(resp).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out, tokens = JevHttpClient("k").ask_many({"x": 1}, {
        "c": Question("choice", "escolha", {"a": "A", "b": "B"}), "n": Question("noul", "verdade?")})
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone" and seen["auth"] == "Bearer k"
    assert seen["body"]["questions"]["c"]["criteria"] == {"a": "A", "b": "B"}
    assert seen["body"]["model"] == "jev-latest"
    assert out["c"].value == "b" and abs(out["n"].confidence - 0.6) < 1e-9 and tokens == 120


def test_jev_fora_do_ar_nao_para_o_circulo(circle):
    class Down:
        source = "jev"

        def ask_many(self, state, questions):
            raise TimeoutError("timeout")

    circle.ctx.dl.jev = Down()
    circle.submit("38,90 ifood almoço")
    r = circle.tick()
    assert not r.errors and circle.store.get("jev_last_error") == "timeout"


def test_jev_em_duvida_passa_para_a_regra_e_fica_registrado(tmp_path):
    from circulo.decision import Decision
    from circulo.loop import Circle

    class JevIndeciso:
        source = "jev"

        def ask_many(self, state, questions):
            return {k: Decision(k, q.kind, (q.options()[0] if q.kind == "choice" else 0.48 if q.kind == "noul" else 0.0),
                                0.04, "jev") for k, q in questions.items()}, 1

    c = Circle(tmp_path, jev=JevIndeciso())
    c.submit("38,90 ifood almoço")
    c.tick()
    fontes = [r["source"] for r in c.store.q("SELECT source FROM decisions WHERE question='input_type'")]
    assert fontes == ["jev", "local"]                    # a dúvida do Jev aparece, e a regra decide
    row = c.store.one("SELECT category FROM ledger")
    assert row["category"] == "delivery"                 # sem a regra, o "não sei" do Jev travaria o lançamento
