"""Canário de falha para os portões natos do developer:abrir_pr que nunca barraram nada.

Pergunta do conselho #130 (auditor): "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda
funciona?" Um diff com marcadores <<<<<<< / ======= / >>>>>>> e um diff sem teste novo são injetados na checagem pura
(sem git nem rede); cada um tem de ser barrado no ponto certo, com a causa certa, e o controle limpo tem de passar.
"""
import time

import pytest

from circulo import canario, neuronios
from circulo.perguntas import _auditor

MARCADOR = "developer:abrir_pr:sem_marcador_de_conflito"
TESTE_NOVO = "developer:abrir_pr:teste_novo"


def test_diff_com_marcadores_de_conflito_e_barrado_com_a_causa_certa():
    linhas = ["<" * 7 + " HEAD", "x = 1", "=" * 7, "x = 2", ">" * 7 + " main"]
    falhas = [r for r in neuronios.portoes_natos_pr(
        [{"filename": "circulo/a.py", "additions": 5, "deletions": 0},
         {"filename": "tests/test_a.py", "additions": 1, "deletions": 0}], {"circulo/a.py": linhas}) if not r.ok]
    assert [f.portao for f in falhas] == ["sem marcador de conflito"]
    assert falhas[0].motivo == "marcadores de conflito em: circulo/a.py"
    assert neuronios.causa_da_falha(falhas) == "conflito_main"


def test_diff_sem_teste_novo_e_barrado_com_a_causa_certa():
    falhas = [r for r in neuronios.portoes_natos_pr([{"filename": "circulo/a.py", "additions": 3, "deletions": 0}],
                                                    {"circulo/a.py": ["x = 1"]}) if not r.ok]
    assert [(f.portao, f.motivo) for f in falhas] == [("teste novo", "nenhum teste novo em tests/")]


@pytest.mark.parametrize("ponto", [MARCADOR, TESTE_NOVO])
def test_canario_barra_a_falha_injetada_e_deixa_passar_o_controle(ponto):
    assert canario.injetar(ponto) == {"ponto": ponto, "velho_falhou": True, "fresco_passou": True, "ok": True}


def test_canario_acusa_portoes_sempre_verdes(monkeypatch):
    monkeypatch.setattr(neuronios, "portoes_natos_pr", lambda arquivos, adicionadas=None: [
        neuronios.Resultado(p, True) for p in ("constituição intacta", "tamanho", "teste novo", "sem marcador de conflito")])
    assert not canario.injetar(MARCADOR)["ok"] and not canario.injetar(TESTE_NOVO)["ok"]


def test_canario_acusa_falha_com_a_causa_errada(monkeypatch):
    monkeypatch.setattr(neuronios, "portoes_natos_pr", lambda arquivos, adicionadas=None: [
        neuronios.Resultado("teste novo", False, "outra coisa"), neuronios.Resultado("sem marcador de conflito", False, "x")])
    assert not canario.injetar(MARCADOR)["velho_falhou"] and not canario.injetar(TESTE_NOVO)["velho_falhou"]


def test_auditor_deixa_de_contar_os_dois_pontos_depois_do_canario(circle):
    s = circle.store
    agora = time.time()
    for ponto in (MARCADOR, TESTE_NOVO, "gate:merge"):
        for _ in range(51):
            s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,created_at) VALUES(0,?,'pr',1,?)", (ponto, agora))
    assert sorted(_auditor(s, agora)[0].evidencia["pontos_que_nunca_falharam"]) == sorted([MARCADOR, TESTE_NOVO, "gate:merge"])

    canario.rodar(s, now=agora)
    assert {(r["ponto"], r["ok"]) for r in s.q("SELECT ponto, ok FROM canarios")} == {(MARCADOR, 1), (TESTE_NOVO, 1)}
    assert _auditor(s, agora)[0].evidencia["pontos_que_nunca_falharam"] == ["gate:merge"]
