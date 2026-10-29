"""Lição #26: o reparo rodava o pytest num id inventado ('ERROR: file or directory not found'). O id é conferido por
`ast` antes (arquivo, classes, função, sem o sufixo `[...]`), e a recusa devolve os `test_*` reais do arquivo."""
import json
import time
from pathlib import Path

from circulo import fatiador
from circulo.developer import (ALVO_INEXISTENTE, alvo_coletado, alvo_pytest_existe, estimar_passos, limiar_calibrado,
                               limiar_de_passos, listar_testes)
from circulo.licoes import assinatura_de
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos, criar_portao
from circulo.reparo import REPARO

from test_fatiador import preparar, subs
from test_self_dev import repo  # noqa: F401 — fixture do repositório

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


COM_INIT = '''
class TestComInit:
    def __init__(self):
        pass

    def test_a(self):
        pass


def test_existe():
    pass
'''


def test_licao_26_id_que_o_ast_ve_mas_o_pytest_nao_coleta(tmp_path):
    """lição #26 (pergunta #482): classe com `__init__` passa no `ast`, mas o pytest não a coleta."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_c.py").write_text(COM_INIT)
    assert alvo_pytest_existe(tmp_path, "tests/test_c.py::TestComInit::test_a")
    assert not alvo_coletado(tmp_path, "tests/test_c.py::TestComInit::test_a")
    assert alvo_coletado(tmp_path, "tests/test_c.py::test_existe")


def test_licao_26_reparo_nao_roda_o_pytest_no_id_nao_coletado_e_registra_uma_causa(circle, tmp_path):
    """lição #26: o id que a coleta não acha não roda; vira uma única lição developer:reparo:alvo_inexistente, seja
    qual for o nome do teste, e a recusa leva os testes reais do arquivo."""
    s = circle.store
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_c.py").write_text(COM_INIT)
    (tmp_path / "tests" / "test_vigia_trava_estado.py").write_text("def test_trava():\n    pass\n")
    for alvo in ("tests/test_c.py::TestComInit::test_a", "tests/test_vigia_trava_estado.py::test_200_decisoes_x"):
        criar_portao(s, ABRIR_PR, "comando", {"argv": ["-m", "pytest", "-q", alvo]}, f"teste {alvo}", None)
    r1, r2 = avaliar_aprendidos(s, ABRIR_PR, tmp_path, {}, {})
    assert r1.ok and "recusa alvo_inexistente" in r1.motivo and "pytest não rodou" in r1.motivo
    assert "test_existe" in r1.motivo and r2.ok and "test_trava" in r2.motivo
    lics = s.q("SELECT assinatura, ocorrencias FROM licoes")
    assert [(x["assinatura"], x["ocorrencias"]) for x in lics] == [(ALVO_INEXISTENTE, 2)]
    assert {v["causa"] for v in s.q("SELECT causa FROM verificacoes WHERE ponto=?", (REPARO,))} == {"alvo_inexistente"}


def test_licao_26_file_or_directory_not_found_tem_assinatura_unica():
    """lição #26: lições #31 e #35 eram a mesma causa com nomes de teste diferentes."""
    sigs = {assinatura_de(REPARO, f"- aprendido#{n}: teste {alvo}: ERROR: {erro}: {alvo}\n\nno tests ran in 0.01s")
            for n, alvo in ((3, "tests/test_vigia_trava_estado.py::test_200_decisoes_x"), (9, "tests/test_b.py::test_y"))
            for erro in ("file or directory not found", "not found")}
    assert sigs == {ALVO_INEXISTENTE}


MAX_TURNS = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 41,
                        "terminal_reason": "max_turns"})


def test_licao_59_estimar_passos_com_entradas_conhecidas():
    """lição #59: o Developer parava no máximo de passos (38 em 709). A fração prevista sai por regra, antes de rodar."""
    assert estimar_passos([], [], 40) == 0.2                                         # ler, testar, lint, commit
    assert estimar_passos(["circulo/a.py", "circulo/b.py"], ["f", "g", "h", "i", "j"], 40) == 0.875
    assert estimar_passos(["circulo/a.py"], ["f"], 80) == 17 / 80
    assert limiar_de_passos([]) == limiar_de_passos([0.3, 0.4]) == 0.8                # poucas amostras: o palpite inicial
    assert limiar_de_passos([0.9, 0.5, 0.7, 1.0, 0.6]) == 0.5                         # p20 das que estouraram


def test_licao_59_risco_de_passos_acima_do_limiar_vai_ao_fatiador_antes(circle, repo):  # noqa: F811
    """lição #59: 2 módulos e 5 funções não passam dos limites do fatiador, mas preveem 87,5% dos passos: divide."""
    item, dev, agent, llm = preparar(circle, repo)
    circle.store.x("UPDATE roadmap SET detalhe=? WHERE id=?", (
        "Em circulo/alfa.py mudar contar() e somar() e medir(); em circulo/beta.py mudar ler() e gravar()", item))
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    partes = subs(circle, item)
    assert len(partes) == 2 and alvo == partes[0]["id"] and llm.prompts == []
    assert (circle.store.get("developer_passos") or {})["Item grande demais"]["fracao"] == 0.875


def test_licao_59_parada_no_maximo_de_passos_devolve_a_tarefa_ao_fatiador(circle, repo):  # noqa: F811
    """lição #59, reserva: a tarefa que parou no máximo de passos não volta inteira; o fatiador a divide."""
    item, dev, agent, llm = preparar(circle, repo)
    circle.licoes.verificar("developer:agente", False, sujeito="Item grande demais", motivo=MAX_TURNS, licao=False)
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, b = subs(circle, item)
    assert alvo == a["id"] and len(llm.prompts) == 1 and "máximo de passos" in llm.prompts[0]
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"


def test_licao_59_limiar_recalibrado_pelas_tarefas_que_estouraram(circle):
    s = circle.store
    assert limiar_calibrado(s) == 0.8
    s.set("developer_passos", {f"t{i}": {"fracao": f, "limite": 40} for i, f in enumerate([0.9, 0.5, 0.7, 1.0, 0.6, 0.2])})
    for i in range(5):
        circle.licoes.verificar("developer:agente", False, sujeito=f"t{i}", motivo=MAX_TURNS, licao=False)
    circle.licoes.verificar("developer:agente", False, sujeito="t5", motivo="AssertionError", licao=False)   # outra causa
    assert limiar_calibrado(s) == 0.5
