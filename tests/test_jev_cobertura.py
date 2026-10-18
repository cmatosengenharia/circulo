"""O loop confere se cada pergunta ao Jev usa o que a API oferece (critérios nos dois lados, situações, não graus)."""
import json

from circulo.decision import SN, JevHttpClient, Question
from circulo.jev_cobertura import cobertura


def test_toda_pergunta_ao_jev_tem_criterios_descritos():
    c = cobertura()
    sem = [f for f in c["faltam"] if "criterios" in f["falta"]]
    assert not sem, f"perguntas sem critérios (doc do Jev: descreva a situação de cada resposta): {sem}"
    assert c["total"] >= 30


def test_cliente_envia_criterios_do_noul_e_guarda_legenda_do_score(monkeypatch):
    enviado = {}

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        enviado.update(json.loads(req.data))
        return Resp({"model": "jev-1.13.0", "answers": {
            "s": {"type": "noul", "noul": 0.9},
            "n": {"type": "score", "score": 1.4, "confidence": 0.4, "probabilities": {"0": 0.0, "1": 0.6, "2": 0.4},
                  "legend": {"0": "a", "1": "b", "2": "c"}}}, "usage": {"input_tokens": 10}})
    monkeypatch.setattr("circulo.decision.urllib.request.urlopen", fake_urlopen)
    out, _ = JevHttpClient("k").ask_many({"x": 1}, {"s": Question("noul", "sim?", SN("quando sim", "quando não")),
                                                   "n": Question("score", "nível?", ("a", "b", "c"))})
    assert enviado["questions"]["s"]["criteria"] == {"true": "quando sim", "false": "quando não"}
    assert out["n"].probabilities["1"] == 0.6 and out["n"].probabilities["_legend"]["2"] == "c"


def test_decisao_guarda_a_distribuicao(circle):
    from circulo.decision import Decision
    circle.ctx.dl._log(Decision("idle_task", "choice", "resumo", 0.3, "jev", {"resumo": 0.5, "regressao": 0.5}))
    r = circle.store.one("SELECT probabilidades FROM decisions WHERE question='idle_task' ORDER BY id DESC")
    assert json.loads(r["probabilidades"]) == {"resumo": 0.5, "regressao": 0.5}
