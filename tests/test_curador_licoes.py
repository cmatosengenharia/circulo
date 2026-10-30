"""Curador de lições (pergunta do conselho #190): lição cujo node id de pytest citado não existe em tests/ fecha com a
causa, e reabre se o teste citado aparecer."""
import subprocess
import time

from circulo.curador_licoes import CAUSA, inexistentes, node_ids

SUMIDO = "tests/test_vigia_trava_estado.py::test_200_decisoes_de_vigia_trava_saem_da_duvida_concordando_com_a_regra"


def git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


def commit(repo, arquivos: dict[str, str]):
    for nome, texto in arquivos.items():
        (repo / nome).parent.mkdir(parents=True, exist_ok=True)
        (repo / nome).write_text(texto)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")


def licao(store, lid, descricao, status="aberta", assinatura=None):
    agora = time.time()
    store.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,"
            "primeira_tick,ultima_tick,created_at,updated_at,camada) VALUES(?,?,?,?,?,?,?,1,0,0,0,?,?,'regra')",
            (lid, assinatura or f"developer:abrir_pr:x{lid}", "developer:abrir_pr", "trabalho", descricao,
             f"Não repetir: {descricao}", status, agora, agora))


def status(store, lid):
    return store.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"]


def test_node_id_citado_no_texto_e_conferido_pelo_ast():
    fontes = {"tests/test_vigia.py": "class TestX:\n    def test_m(self):\n        pass\n\ndef test_a():\n    pass\n"}
    assert node_ids(f"ERROR: file or directory not found: {SUMIDO} (x)") == [SUMIDO]
    assert inexistentes(f"falhou {SUMIDO}", fontes.get) == [SUMIDO]
    assert inexistentes("falhou tests/test_vigia.py::test_a e tests/test_vigia.py::TestX::test_m", fontes.get) == []
    assert inexistentes("tests/test_vigia.py::test_zz", fontes.get) == ["tests/test_vigia.py::test_zz"]
    assert inexistentes("cortado no fim: tests/test_vigia.py::test_", fontes.get) == []      # nome truncado de um que existe
    assert inexistentes("sem node id nenhum", fontes.get) == []


def test_licoes_26_27_35_com_teste_inexistente_fecham_e_reabrem_se_ele_aparecer(circle, tmp_path):
    """Lição #26, lição #27 e lição #35: a mesma causa raiz, o node id citado não existe ('file or directory not found')."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"tests/test_vigia.py": "def test_existe():\n    assert False\n"})
    s, L = circle.store, circle.licoes
    L.repo = repo
    for lid in (26, 27, 35):
        licao(s, lid, f"developer:abrir_pr: ERROR: file or directory not found: {SUMIDO[:60 + lid]}")
    licao(s, 40, "developer:testes: FAILED tests/test_vigia.py::test_existe - assert False")
    licao(s, 41, "planejador: resposta sem JSON válido")
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["obsoleta"] * 3
    assert all(s.one("SELECT prevencao FROM licoes WHERE id=?", (i,))["prevencao"].startswith(CAUSA) for i in (26, 27, 35))
    assert (status(s, 40), status(s, 41)) == ("aberta", "aberta")       # teste que existe e lição sem node id ficam
    assert s.one("SELECT COUNT(*) n FROM licoes WHERE status IN ('aberta','reincidente')")["n"] == 2
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["obsoleta"] * 3   # não reincide enquanto o teste não existir
    commit(repo, {"tests/test_vigia_trava_estado.py": f"def {SUMIDO.split('::')[1]}():\n    pass\n"})
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["aberta"] * 3     # o teste citado apareceu: a lição volta


def test_sem_repositorio_nao_fecha_nada(circle):
    s, L = circle.store, circle.licoes
    L.repo = None
    licao(s, 26, f"ERROR: file or directory not found: {SUMIDO}")
    L.revisar()
    assert status(s, 26) == "aberta"
