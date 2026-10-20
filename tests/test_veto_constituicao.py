"""Item do planejador que cita a constituição é vetado antes de virar trabalho do Developer (pergunta do conselho #26),
e cada falha de developer:abrir_pr grava a causa normalizada (constituição|conflito_main|ci|outra) para o Vigia agrupar."""
import json
import time

import pytest
from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo import planejador as pl
from circulo.neuronios import ABRIR_PR, Resultado, causa_da_falha, cita_constituicao
from circulo.planejador import Planejador


class LLMItem:
    def __init__(self, detalhe):
        self.detalhe, self.chamadas = detalhe, 0

    def complete(self, system, prompt, max_tokens):
        self.chamadas += 1
        return json.dumps({"titulo": "Item novo da pergunta do operador", "detalhe": self.detalhe, "sucesso": "0 falhas"}), 400


def _pergunta(circle):
    t = time.time()
    return circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) "
                          "VALUES('k','operador','q?','valida','loop',0.5,?,?)", (t, t))


@pytest.mark.parametrize("detalhe", [
    "Em circulo/self_dev.py, mudar o portao_pr para registrar a causa.",
    "Ajustar self_dev.py para gravar a causa.",                 # nome solto é ambíguo: suspeito
    "Adicionar um passo em .github/workflows/ci.yml.",
])
def test_item_que_cita_a_constituicao_e_vetado_antes_do_developer(circle, detalhe):
    pid = _pergunta(circle)
    circle.ctx.dl.llm = LLMItem(detalhe)
    antes = circle.store.one("SELECT COUNT(*) n FROM roadmap")["n"]
    assert Planejador(circle.ctx, None).run(autorizado=True) is None
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes      # nada chega ao Developer
    u = circle.store.get(pl.TENTATIVAS)["ultima"]
    assert u["pergunta_id"] == pid and u["desfecho"] == "descartada" and u["motivo"].startswith("constituição")
    assert circle.store.one("SELECT status FROM perguntas WHERE id=?", (pid,))["status"] == "descartada"


def test_item_fora_da_constituicao_segue_para_o_roteiro(circle):
    _pergunta(circle)
    circle.ctx.dl.llm = LLMItem("Em circulo/reparo.py, gravar a causa de cada falha.")
    assert Planejador(circle.ctx, None).run(autorizado=True)
    assert circle.store.get(pl.TENTATIVAS)["ultima"]["desfecho"] == "virou_item"


def test_cita_constituicao_le_a_lista_do_gate():
    assert cita_constituicao("mexer em circulo/self_dev.py e circulo/merge_gate.py") == ["circulo/self_dev.py", "circulo/merge_gate.py"]
    assert cita_constituicao("corpo.py") == ["corpo.py"]
    assert cita_constituicao("circulo/corpo_caminho.py e circulo/reparo.py") == []
    assert cita_constituicao("") == []


def test_causa_normalizada_de_cada_portao():
    falha = lambda nome: [Resultado(nome, False, "x")]   # noqa: E731
    assert causa_da_falha(falha("constituição intacta")) == "constituição"
    assert causa_da_falha(falha("sem marcador de conflito")) == "conflito_main"
    assert causa_da_falha(falha("lint e testes (iguais ao CI)")) == "ci"
    assert causa_da_falha([Resultado("aprendido#3: lint B905", False, "x", 3)]) == "ci"
    assert causa_da_falha(falha("teste novo")) == "outra"
    assert causa_da_falha([*falha("teste novo"), *falha("constituição intacta")]) == "constituição"


def test_falha_de_abrir_pr_grava_a_causa(circle, repo, tmp_path):  # noqa: F811
    erro_recorrente(circle)
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=99))
    assert dev.run_once().status == "testes_falharam" and gh.prs == []
    r = circle.store.q("SELECT causa FROM verificacoes WHERE ponto=? AND ok=0", (ABRIR_PR,))
    assert [x["causa"] for x in r] == ["ci"]
