"""Lição #27: pytest com alvo que não existe na main nem num item pendente do roteiro ('file or directory not found')
não é erro novo: a lição fica obsoleta com a causa e a contagem não sobe."""
import subprocess
import time

from circulo.licoes import Licoes

MOTIVO = "- aprendido#3: teste: ERROR: file or directory not found: {alvo}\n\nno tests ran in 0.01s"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_existe.py").write_text("def test_x():\n    assert True\n")

    def git(*a):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    return repo


def test_licao_27_alvo_inexistente_fica_obsoleta_e_a_contagem_em_1(circle, tmp_path):
    L = Licoes(circle.store, repo=_repo(tmp_path))
    agora = time.time()       # o item que conserta a lição cita o erro, mas não cria o arquivo
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES"
                   "('Lição #27','ERROR: file or directory not found: tests/inexistente.py::x','erro','pendente','',1,?,?)",
                   (agora, agora))
    for _ in range(3):
        L.verificar("developer:abrir_pr", False, sujeito="item", motivo=MOTIVO.format(alvo="tests/inexistente.py::x"))
    lic = circle.store.one("SELECT * FROM licoes")
    assert lic["status"] == "obsoleta" and lic["ocorrencias"] == 1
    assert "tests/inexistente.py" in lic["prevencao"] and "não existe" in lic["prevencao"]
    assert not L.bloqueia_evolucao()


def test_licao_27_alvo_na_main_ou_em_item_pendente_conta_normalmente(circle, tmp_path):
    L = Licoes(circle.store, repo=_repo(tmp_path))
    agora = time.time()
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES('Criar tests/test_novo.py','d','erro','pendente','',1,?,?)", (agora, agora))
    for alvo in ("tests/test_existe.py::y", "tests/test_novo.py::z"):
        for _ in range(2):
            L.verificar("developer:abrir_pr", False, sujeito="item", motivo=MOTIVO.format(alvo=alvo))
    rows = circle.store.q("SELECT status, ocorrencias FROM licoes")
    assert [(r["status"], r["ocorrencias"]) for r in rows] == [("aberta", 4)]
