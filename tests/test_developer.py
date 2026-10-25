"""Lição #26: o reparo rodava o pytest num id inventado ('ERROR: file or directory not found'). O id é conferido por
`ast` antes (arquivo, classes, função, sem o sufixo `[...]`), e a recusa devolve os `test_*` reais do arquivo."""
import time
from pathlib import Path

from circulo.developer import alvo_pytest_existe, listar_testes
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos, criar_portao

RAIZ = Path(__file__).resolve().parent.parent
REAL = "test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra"

MODULO = '''
import pytest


def test_solto():
    pass


@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    pass


class TestFora:
    def test_metodo(self):
        pass

    class TestDentro:
        async def test_fundo(self):
            pass


class TestHerda(Base):
    pass
'''


def _repo(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_m.py").write_text(MODULO)
    return tmp_path


def test_licao_26_id_inventado_nao_existe():
    assert not alvo_pytest_existe(RAIZ, f"tests/test_vigia_trava_estado.py::{REAL}")
    assert not alvo_pytest_existe(RAIZ, "tests/test_jev_replay.py::test_200_decisoes_...")


def test_id_valido_existe():
    assert alvo_pytest_existe(RAIZ, f"tests/test_jev_replay.py::{REAL}")
    assert alvo_pytest_existe(RAIZ, "tests/test_jev_replay.py")


def test_id_de_classe_e_de_classe_aninhada(tmp_path):
    raiz = _repo(tmp_path)
    assert alvo_pytest_existe(raiz, "tests/test_m.py::TestFora::test_metodo")
    assert alvo_pytest_existe(raiz, "tests/test_m.py::TestFora::TestDentro::test_fundo")
    assert alvo_pytest_existe(raiz, "tests/test_m.py::TestFora")
    assert alvo_pytest_existe(raiz, "tests/test_m.py::TestHerda::test_da_base")      # herdado: o ast não vê, não recusa
    assert not alvo_pytest_existe(raiz, "tests/test_m.py::TestFora::test_solto")
    assert not alvo_pytest_existe(raiz, "tests/test_m.py::test_metodo")
    assert not alvo_pytest_existe(raiz, "tests/test_m.py::TestSumida::test_metodo")


def test_id_parametrizado(tmp_path):
    raiz = _repo(tmp_path)
    assert alvo_pytest_existe(raiz, "tests/test_m.py::test_param[1]")
    assert alvo_pytest_existe(raiz, "tests/test_m.py::test_param[a::b-2]")
    assert not alvo_pytest_existe(raiz, "tests/test_m.py::test_outro[1]")
    assert listar_testes(raiz, "tests/test_m.py") == [
        "test_solto", "test_param", "TestFora::test_metodo", "TestFora::TestDentro::test_fundo"]


def test_licao_26_reparo_recusa_alvo_inexistente_sem_rodar_o_pytest(circle, tmp_path):
    s, agora = circle.store, time.time()
    lid = s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,"
              "updated_at) VALUES('developer:reparo:x','developer','trabalho','d','p','aberta',1,0,?,?)", (agora, agora))
    criar_portao(s, ABRIR_PR, "comando", {"argv": ["-m", "pytest", "-q", "tests/test_m.py::test_inventado"]},
                 "teste tests/test_m.py::test_inventado", licao_id=lid)
    [r] = avaliar_aprendidos(s, ABRIR_PR, _repo(tmp_path), {}, {})
    assert r.ok and "alvo_inexistente" in r.motivo and "não existe mais" in r.motivo
    assert "test_solto" in r.motivo and "TestFora::test_metodo" in r.motivo
    assert s.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"] == "obsoleta"
