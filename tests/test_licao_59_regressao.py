"""Lição #59 (developer:agente:maximo_de_passos): o estouro de passos do agente não se reproduz sem LLM, mas o portão
que reage a ele já tem teste (tests/test_developer.py::test_licao_59_*, PR #214). A lição seguia sem_prevencao e
reincidindo porque nada ligava a assinatura a esse teste: a causa precisa apontar para ele."""
from pathlib import Path

from circulo.causas import node_por_causa
from circulo.developer import alvo_pytest_existe
from circulo.prevencao import checagem_de, cobrar_teste, exigir

RAIZ = Path(__file__).resolve().parent.parent


def test_licao_59_assinatura_do_maximo_de_passos_aponta_para_o_teste_do_fatiador():
    node = node_por_causa("developer:agente:maximo_de_passos")
    assert node and "test_licao_59_" in node and alvo_pytest_existe(RAIZ, node)


def test_licao_59_sem_prevencao_sai_com_a_checagem_e_nao_cobra_outro_item(circle):
    s = circle.store
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,created_at,updated_at,camada) VALUES(59,'developer:agente:maximo_de_passos','developer:agente',"
        "'estrutural','developer:agente: maximo de passos','Não repetir','sem_prevencao',21,12,0,0,0,0,'regra')")
    assert checagem_de(s, dict(s.one("SELECT * FROM licoes WHERE id=59")))
    assert exigir(s, 10, 0.0) == ["lição #59 validada"]
    r = s.one("SELECT status, prevencao FROM licoes WHERE id=59")
    assert r["status"] == "validada" and "tests/test_developer.py::test_licao_59_" in r["prevencao"]
    assert cobrar_teste(s) == []
