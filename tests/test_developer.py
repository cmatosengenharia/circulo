"""Lição #26: o reparo rodava o pytest num id inventado ('ERROR: file or directory not found'). O id é conferido por
`ast` antes (arquivo, classes, função, sem o sufixo `[...]`), e a recusa devolve os `test_*` reais do arquivo."""
import io
import json
import time
from contextlib import redirect_stdout
from pathlib import Path

from circulo import developer, fatiador
from circulo.developer import (ALVO_INEXISTENTE, CONVENCOES, alvo_coletado, alvo_pytest_existe, convencoes,
                               estimar_passos, limiar_calibrado, limiar_de_passos, listar_testes, no_controle,
                               relatorio_convencoes)
from circulo.licoes import assinatura_de
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos, criar_portao
from circulo.registro import registrar as registrar_llm
from circulo.reparo import REPARO, DeveloperComReparo

from test_fatiador import preparar, subs
from test_self_dev import TEST_CMD, FakeGH, FixAgent, erro_recorrente, repo  # noqa: F401 — fixture do repositório

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


AGENTS = "# Convenções\n\n## Testes\nrode `python -m pytest -q`\n\n```sh\n# não é seção\n```\n\n### Armadilhas\nnada\n"


def test_convencoes_hash_secoes_e_grupo_de_controle(tmp_path):
    """Sem AGENTS.md nada entra; com ele, hash e títulos das seções; o controle (~20%, por título) fica sem o texto."""
    assert convencoes(tmp_path, "t") == {"hash": None, "secoes": [], "com_convencoes": False, "linhas": 0, "bytes": 0,
                                         "texto": ""}
    (tmp_path / "AGENTS.md").write_text(AGENTS)
    com, ctrl = convencoes(tmp_path, "t", fracao_controle=0), convencoes(tmp_path, "t", fracao_controle=1)
    assert com["secoes"] == ["Convenções", "Testes", "Armadilhas"] and com["com_convencoes"]
    assert "rode `python -m pytest -q`" in com["texto"] and com["linhas"] == 11 and com["bytes"] == len(AGENTS.encode())
    assert ctrl["hash"] == com["hash"] and ctrl["secoes"] == [] and not ctrl["com_convencoes"] and ctrl["texto"] == ""
    sorteio = [no_controle(f"tarefa {i}") for i in range(2000)]
    assert sorteio == [no_controle(f"tarefa {i}") for i in range(2000)]          # determinístico
    assert 0.17 < sum(sorteio) / len(sorteio) < 0.23


class GHComCorpo(FakeGH):
    def create_pr(self, head, base, title, body):
        self.corpos = [*getattr(self, "corpos", []), body]
        return super().create_pr(head, base, title, body)


def _pr_com_agents_md(circle, repo, titulo):  # noqa: F811
    (repo / "AGENTS.md").write_text(AGENTS)
    item = erro_recorrente(circle)
    circle.store.x("UPDATE roadmap SET titulo=? WHERE id=?", (titulo, item["id"]))
    agent, gh = FixAgent(), GHComCorpo()
    dev = DeveloperComReparo(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD, lint_cmd=[], fix_cmds=[])
    r = dev.run_once()
    assert r.status == "proposto", r.detalhe
    ev = circle.store.get(CONVENCOES)[titulo]
    assert ev["hash"] == convencoes(repo, titulo)["hash"] and f"`{ev['hash']}`" in gh.corpos[0]
    return ev, agent.tasks[0], gh.corpos[0]


def test_pr_do_developer_lista_hash_e_secoes_do_agents_md(circle, repo):  # noqa: F811
    """Todo PR do Developer leva o evento da tarefa: hash do AGENTS.md, seções injetadas e com_convencoes."""
    assert not no_controle("Corrigir soma")
    ev, prompt, corpo = _pr_com_agents_md(circle, repo, "Corrigir soma")
    assert ev["com_convencoes"] and ev["secoes"] == ["Convenções", "Testes", "Armadilhas"]
    assert "rode `python -m pytest -q`" in prompt
    assert "seções injetadas: Convenções, Testes, Armadilhas (com_convencoes=1)" in corpo


def test_pr_do_grupo_de_controle_registra_o_hash_sem_injetar(circle, repo):  # noqa: F811
    assert no_controle("Corrigir soma com convenções")
    ev, prompt, corpo = _pr_com_agents_md(circle, repo, "Corrigir soma com convenções")
    assert not ev["com_convencoes"] and ev["secoes"] == [] and "rode `python -m pytest -q`" not in prompt
    assert "grupo de controle, nada injetado (com_convencoes=0)" in corpo


def test_relatorio_compara_falha_e_tokens_com_e_sem_convencoes(circle):
    s = circle.store
    ev = {"hash": "abc", "linhas": 10, "bytes": 400, "em": time.time()}
    s.set(CONVENCOES, {"a": {**ev, "secoes": ["X"], "com_convencoes": True},
                       "b": {**ev, "secoes": ["X"], "com_convencoes": True},
                       "c": {**ev, "secoes": [], "com_convencoes": False},
                       "d": {**ev, "hash": None, "bytes": 0, "secoes": [], "com_convencoes": False}})   # sem arquivo: fora
    for titulo, ok, tokens in (("a", True, 1100), ("b", False, 1300), ("c", True, 1000), ("d", False, 5)):
        circle.licoes.verificar("developer:agente", ok, sujeito=titulo, motivo="" if ok else "x", licao=False)
        registrar_llm(s, tick=0, project_id=None, papel="developer", modelo="m", tokens=tokens, ok=ok, entrada=titulo)
    r = relatorio_convencoes(s)
    assert r["com"] == {"tarefas": 2, "taxa_falha": 0.5, "tokens_por_tarefa": 1200, "bytes_injetados": 400}
    assert r["controle"] == {"tarefas": 1, "taxa_falha": 0.0, "tokens_por_tarefa": 1000, "bytes_injetados": 0}
    assert r["custo_relativo"] == 1.2 and r["aceito"] is False                   # falha pior que o controle


def test_relatorio_de_convencoes_pela_linha_de_comando_so_da_janela(circle):
    """`python -m circulo.developer --dias 7` imprime o relatório só com as tarefas da janela."""
    s, agora = circle.store, time.time()
    ev = {"hash": "abc", "linhas": 10, "bytes": 400, "secoes": [], "com_convencoes": False}
    s.set(CONVENCOES, {"nova": {**ev, "em": agora}, "velha": {**ev, "em": agora - 8 * 86400}})
    for titulo in ("nova", "velha"):
        circle.licoes.verificar("developer:agente", True, sujeito=titulo, motivo="", licao=False)
    saida = io.StringIO()
    with redirect_stdout(saida):
        developer.main(["--data", str(Path(s.path).parent), "--dias", "7"])
    r = json.loads(saida.getvalue())
    assert r["controle"]["tarefas"] == 1 and r["com"]["tarefas"] == 0 and r["aceito"] is None
